import math
import uuid
from dataclasses import dataclass

import numpy as np
import structlog
from sklearn.cluster import KMeans, MiniBatchKMeans
from tqdm.asyncio import tqdm

logger = structlog.get_logger(__name__)


def cosine_similarity_func(a: list[float], b: list[float]) -> float:
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


@dataclass(frozen=True)
class RelevantTracesGroup:
    traces: list[str]
    avg_similarity: float | None


@dataclass(frozen=True)
class TracesCluster:
    traces: list[str]
    embeddings: list[list[float]]


# How many times max to re-group singles to increase group count
EMBEDDINGS_CLUSTERING_MAX_RECURSION: int = 3
# How many additional recursions allowed if the tail is too large (loose traces)
EMBEDDINGS_CLUSTERING_MAX_TAIL_RECURSION: int = 3
# If the tail is larger than that - try to cluster once more with more loose approach
EMBEDDINGS_CLUSTERING_MAX_TAIL_PERCENTAGE: float = 0.50
# Split embeddings into chunks to speed up clustering
EMBEDDINGS_CLUSTERING_CHUNK_SIZE: int = 1000  # Increasing from default 25
# Expected average similarity between embeddings to group them
EMBEDDINGS_COSINE_SIMILARITY: float = 0.72  # Lowering from the default 0.95
# How many times to try to group until to stop
EMBEDDINGS_CLUSTERING_ITERATIONS: int = 5
# How many times to try to group when trying to decrease the tail (too large, loose traces)
EMBEDDINGS_CLUSTERING_MAX_TAIL_ITERATIONS: int = 1
# Expected minimal number of traces per group when grouping embeddings
EXPECTED_SUGGESTIONS_PER_EMBEDDINGS_GROUP: int = 25  # Increasing from default 5
# Max traces per group to avoid large loosely-related groups
MAX_SUGGESTIONS_PER_EMBEDDINGS_GROUP: int = 100
# How to decrease the similarity between embeddings to group them with each iteration,
# to increase the number of groups and improve the user experience
EMBEDDINGS_COSINE_SIMILARITY_DECREASE: float = 0.01


# Results (1000-items run)

# 15-sized groups:
# 2025-10-19 15:20:25 [info     ] INPUT
# 2025-10-19 15:20:25 [info     ] Clustering chunk size: 1000
# 2025-10-19 15:20:25 [info     ] Clustering cosine similarity: 0.72
# 2025-10-19 15:20:25 [info     ] Expected traces per embeddings group: 15
# 2025-10-19 15:20:25 [info     ] CLUSTERING RESULTS
# 2025-10-19 15:20:25 [info     ] Groups count: 70
# 2025-10-19 15:20:25 [info     ] Singles count: 506
# 2025-10-19 15:20:25 [info     ] Avg cosine similarity: 0.7435714285714285

# 25-sized groups:
# 2025-10-19 15:17:40 [info     ] INPUT
# 2025-10-19 15:17:40 [info     ] Clustering chunk size: 1000
# 2025-10-19 15:17:40 [info     ] Clustering cosine similarity: 0.72
# 2025-10-19 15:17:40 [info     ] Expected traces per embeddings group: 25
# 2025-10-19 15:17:40 [info     ] CLUSTERING RESULTS
# 2025-10-19 15:17:40 [info     ] Groups count: 32
# 2025-10-19 15:17:40 [info     ] Singles count: 598
# 2025-10-19 15:17:40 [info     ] Avg cosine similarity: 0.720625

# 50-sized groups:
# 2025-10-19 18:03:19 [info     ] INPUT
# 2025-10-19 18:03:19 [info     ] Clustering chunk size: 1000
# 2025-10-19 18:03:19 [info     ] Clustering cosine similarity: 0.72
# 2025-10-19 18:03:19 [info     ] Expected traces per embeddings group: 50
# 2025-10-19 18:03:19 [info     ] CLUSTERING RESULTS
# 2025-10-19 18:03:19 [info     ] Groups count: 7
# 2025-10-19 18:03:19 [info     ] Singles count: 907
# 2025-10-19 18:03:19 [info     ] Avg cosine similarity: 0.7099999999999999

# Results (6636-items run in 1000 chunks)

# 15-sized groups:
# 2025-10-19 18:27:09 [info     ] INPUT
# 2025-10-19 18:27:09 [info     ] Clustering chunk size: 1000
# 2025-10-19 18:27:09 [info     ] Clustering cosine similarity: 0.72
# 2025-10-19 18:27:09 [info     ] Expected traces per embeddings group: 15
# 2025-10-19 18:27:09 [info     ] CLUSTERING RESULTS
# 2025-10-19 18:27:09 [info     ] Groups count: 582
# 2025-10-19 18:27:09 [info     ] Singles count: 1088
# 2025-10-19 18:27:09 [info     ] Avg cosine similarity: 0.7607044673539523

# 25-sized groups:
# 2025-10-19 20:04:56 [info     ] INPUT
# 2025-10-19 20:04:56 [info     ] Clustering chunk size: 1000
# 2025-10-19 20:04:56 [info     ] Clustering cosine similarity: 0.72
# 2025-10-19 20:04:56 [info     ] Expected traces per embeddings group: 25
# 2025-10-19 20:04:56 [info     ] CLUSTERING RESULTS
# 2025-10-19 20:04:56 [info     ] Groups count: 329
# 2025-10-19 20:04:56 [info     ] Singles count: 1960
# 2025-10-19 20:04:56 [info     ] Avg cosine similarity: 0.7536778115501521
# 2025-10-19 20:04:58 [info     ]


class KmeansClusterizer:
    @classmethod
    def clusterize_traces(
        cls,
        embedded_traces: list[str],
        embeddings: list[list[float]],
        max_tail_size: int,
        pre_combined_groups: dict[str, RelevantTracesGroup] | None = None,
        iteration: int = 0,
    ) -> tuple[dict[str, RelevantTracesGroup], TracesCluster]:
        """
        Wrapper for clusterizing traces, to allow tracking stats
        for clusterization iterations only once, on final iteration.
        """
        # Assuming the input is sorted alphabetically in hope to improve grouping quality
        return cls._clusterize_traces(
            embedded_traces=embedded_traces,
            embeddings=embeddings,
            max_tail_size=max_tail_size,
            pre_combined_groups=pre_combined_groups,
            iteration=iteration,
        )

    @classmethod
    def _clusterize_traces(
        cls,
        embedded_traces: list[str],
        embeddings: list[list[float]],
        max_tail_size: int,
        pre_combined_groups: dict[str, RelevantTracesGroup] | None,
        iteration: int,
        cosine_similarity: float = EMBEDDINGS_COSINE_SIMILARITY,
        clustering_iterations: int = EMBEDDINGS_CLUSTERING_ITERATIONS,
    ) -> tuple[dict[str, RelevantTracesGroup], TracesCluster]:
        groups, singles = cls._clusterize_traces_iteration(
            embedded_traces=embedded_traces,
            embeddings=embeddings,
            iteration=iteration,
            cosine_similarity=cosine_similarity,
            clustering_iterations=clustering_iterations,
        )
        combined_groups: dict[str, RelevantTracesGroup] = {}
        # If pre-combined groups are provided - add them to the combined groups
        if pre_combined_groups:
            groups = [pre_combined_groups, *groups]
        for group_set in groups:
            combined_groups = {**combined_groups, **group_set}
        # Combine the singles in the expected format
        combined_singles = TracesCluster(traces=[], embeddings=[])
        for single in singles:
            combined_singles.traces.extend(single.traces)
            combined_singles.embeddings.extend(single.embeddings)
        # If there are still iterations left - iterate again
        if iteration < EMBEDDINGS_CLUSTERING_MAX_RECURSION:
            return cls._clusterize_traces(
                embedded_traces=combined_singles.traces,
                embeddings=combined_singles.embeddings,
                max_tail_size=max_tail_size,
                pre_combined_groups=combined_groups,
                iteration=iteration + 1,
            )
        # If the iterations exhausted and the tail is acceptable - return the results
        if len(combined_singles.traces) <= max_tail_size:
            return combined_groups, combined_singles
        # If the tail is still too large, but no max tail recursions left - return the results anyway
        if iteration >= (EMBEDDINGS_CLUSTERING_MAX_RECURSION + EMBEDDINGS_CLUSTERING_MAX_TAIL_RECURSION):
            return combined_groups, combined_singles
        # If the tail is still too large and there are max tail recursions left -
        # iterate again with the lowest allowed average similarity
        max_tail_cosine_similarity = round(
            (
                # Calculate the lowest allowed similarity
                EMBEDDINGS_COSINE_SIMILARITY
                - (
                    # First iteration doesn't count (i-0), so decrease the similarity
                    (EMBEDDINGS_CLUSTERING_ITERATIONS - 1) * EMBEDDINGS_COSINE_SIMILARITY_DECREASE
                )
            ),
            2,
        )
        return cls._clusterize_traces(
            embedded_traces=combined_singles.traces,
            embeddings=combined_singles.embeddings,
            max_tail_size=max_tail_size,
            pre_combined_groups=combined_groups,
            iteration=iteration + 1,
            cosine_similarity=max_tail_cosine_similarity,
            clustering_iterations=EMBEDDINGS_CLUSTERING_MAX_TAIL_ITERATIONS,
        )

    @classmethod
    def _clusterize_traces_iteration(
        cls,
        embedded_traces: list[str],
        embeddings: list[list[float]],
        iteration: int,
        cosine_similarity: float,
        clustering_iterations: int,
    ) -> tuple[list[dict[str, RelevantTracesGroup]], list[TracesCluster]]:
        # Split traces into large chunks, and then search for groups within each chunk
        n_clusters = math.ceil(len(embeddings) / EMBEDDINGS_CLUSTERING_CHUNK_SIZE)
        if n_clusters == 1:
            # If it's a single cluster - create it manually
            init_embeddings_clusters = {"single_cluster": TracesCluster(traces=embedded_traces, embeddings=embeddings)}
        else:
            init_embeddings_clusters = cls._calculate_embeddings_clusters(
                embedded_traces=embedded_traces,
                embeddings=embeddings,
                n_clusters=n_clusters,
                minibatch=True,
            )
        return cls._group_multiple_embeddings_clusters(
            init_embeddings_clusters=init_embeddings_clusters,
            iteration=iteration,
            cosine_similarity=cosine_similarity,
            clustering_iterations=clustering_iterations,
        )

    @classmethod
    def _group_multiple_embeddings_clusters(
        cls,
        init_embeddings_clusters: dict[str, TracesCluster],
        iteration: int,
        cosine_similarity: float,
        clustering_iterations: int,
    ) -> tuple[list[dict[str, RelevantTracesGroup]], list[TracesCluster]]:
        groups = []
        singles = []
        # Find groups of traces in each cluster, one by one
        for _i, (_, cluster) in enumerate(
            tqdm(
                init_embeddings_clusters.items(),
                desc=f"Grouping embeddings clusters (iteration: {iteration})",
            )
        ):
            cluster_groups, cluster_singles = cls._group_embeddings_cluster(
                embedded_traces=cluster.traces,
                embeddings=cluster.embeddings,
                cosine_similarity=cosine_similarity,
                clustering_iterations=clustering_iterations,
            )
            groups.append(cluster_groups)
            singles.append(cluster_singles)
        return groups, singles

    @classmethod
    def _group_embeddings_cluster(
        cls,
        embedded_traces: list[str],
        embeddings: list[list[float]],
        cosine_similarity: float,
        clustering_iterations: int,
    ) -> tuple[dict[str, RelevantTracesGroup], TracesCluster]:
        # Define result variables to update with each iteration
        result_relevant_groups: dict[str, RelevantTracesGroup] = {}
        result_singles: TracesCluster = TracesCluster(traces=[], embeddings=[])
        traces_input, embeddings_input = embedded_traces, embeddings
        # An expected average of traces per group.
        embeddings_per_group = EXPECTED_SUGGESTIONS_PER_EMBEDDINGS_GROUP
        # How many times to clusterize until to stop (to disallow while loop to run forever)
        # Decrease the required similarity (- quality) and decrease the cluster size (+ quality) with each iteration
        for similarity_iteration in range(clustering_iterations):
            n_clusters = math.ceil(len(traces_input) / embeddings_per_group)
            # Decrease required similarity to group embeddings with each iteration,
            # to allow more ideas to be grouped and improve the user experience
            avg_similarity_threshold = round(
                cosine_similarity - (EMBEDDINGS_COSINE_SIMILARITY_DECREASE * similarity_iteration),
                2,
            )
            (
                relevant_groups,
                result_singles,
            ) = cls._group_embeddings_cluster_iteration(
                embedded_traces=traces_input,
                embeddings=embeddings_input,
                n_clusters=n_clusters,
                avg_similarity_threshold=avg_similarity_threshold,
            )
            # Save successfully groupped traces
            result_relevant_groups = {**result_relevant_groups, **relevant_groups}
            # If no singles left - nothing to group again, return results
            if not result_singles.traces:
                return result_relevant_groups, result_singles
            # If singles left, but less than a single group - don't group them again
            if len(result_singles.traces) < embeddings_per_group:
                return result_relevant_groups, result_singles
            # If enough singles left - try to clusterize them again
            traces_input, embeddings_input = (
                result_singles.traces,
                result_singles.embeddings,
            )
        # Return the final results
        return result_relevant_groups, result_singles

    @staticmethod
    def _calculate_embeddings_clusters(
        embedded_traces: list[str],
        embeddings: list[list[float]],
        n_clusters: int,
        minibatch: bool,
    ) -> dict[str, TracesCluster]:
        matrix = np.vstack(embeddings)
        if not minibatch:
            kmeans = KMeans(n_clusters=n_clusters, init="k-means++", n_init=10, random_state=42)
        else:
            kmeans = MiniBatchKMeans(n_clusters=n_clusters, init="k-means++", n_init=10, random_state=42)
        kmeans.fit_predict(matrix)
        labels: list[int] = kmeans.labels_
        # Organize clustered traces
        grouped_traces: dict[str, TracesCluster] = {}
        # Generate unique label for each clustering calculation
        unique_label = str(uuid.uuid4())
        for trace, label, emb in zip(embedded_traces, labels, embeddings):
            formatted_label = f"{label}_{unique_label}"
            if formatted_label not in grouped_traces:
                grouped_traces[formatted_label] = TracesCluster(traces=[], embeddings=[])
            grouped_traces[formatted_label].traces.append(trace)
            grouped_traces[formatted_label].embeddings.append(emb)
        return grouped_traces

    @classmethod
    def _group_embeddings_cluster_iteration(
        cls,
        embedded_traces: list[str],
        embeddings: list[list[float]],
        n_clusters: int,
        avg_similarity_threshold: float | None,
    ) -> tuple[dict[str, RelevantTracesGroup], TracesCluster]:
        embeddings_clusters = cls._calculate_embeddings_clusters(
            embedded_traces=embedded_traces,
            embeddings=embeddings,
            n_clusters=n_clusters,
            minibatch=False,
        )
        # Split into relevant groups and singles
        relevant_groups: dict[str, RelevantTracesGroup] = {}
        singles = TracesCluster(traces=[], embeddings=[])
        for group_label, cluster in embeddings_clusters.items():
            if len(cluster.traces) <= 1:
                # Groups with a single idea move to singles automatically
                singles.traces.extend(cluster.traces)
                singles.embeddings.extend(cluster.embeddings)
                continue
            # If avg similarity threshold not provided (init chunking) - don't filter groups
            if not avg_similarity_threshold:
                # Keep the proper-sized groups that are close to each other
                relevant_groups[group_label] = RelevantTracesGroup(
                    traces=cluster.traces,
                    avg_similarity=None,
                )
                continue
            # Calculate average similarity between all traces in the group
            similarities = []
            for trace, emb in zip(cluster.traces, cluster.embeddings):
                for l_trace, l_emb in zip(cluster.traces, cluster.embeddings):
                    if trace != l_trace:
                        similarities.append(cosine_similarity_func(emb, l_emb))
            # Round to 2 symbols after the dot
            if not similarities:
                # TODO: Add some proper logging
                continue
            avg_similarity = round(sum(similarities) / len(similarities), 2)
            # Groups that aren't close enough move to singles
            if avg_similarity < avg_similarity_threshold:
                singles.traces.extend(cluster.traces)
                singles.embeddings.extend(cluster.embeddings)
                continue
            # Avoid having large loosely-connected groups
            if len(cluster.traces) > MAX_SUGGESTIONS_PER_EMBEDDINGS_GROUP:
                singles.traces.extend(cluster.traces)
                singles.embeddings.extend(cluster.embeddings)
                continue
            # Keep the proper-sized groups that are close to each other
            relevant_groups[group_label] = RelevantTracesGroup(
                # Don't save embeddings, as the group is already relevant,
                # so won't go through the clusterization again
                traces=cluster.traces,
                avg_similarity=avg_similarity,
            )
        return relevant_groups, singles
