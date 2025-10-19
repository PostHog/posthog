import math
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import structlog
from sklearn.cluster import KMeans, MiniBatchKMeans
from tqdm.asyncio import tqdm

logger = structlog.get_logger(__name__)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


@dataclass(frozen=True)
class RelevantSuggestionsGroup:
    suggestions: list[str]
    avg_distance: float | None


@dataclass(frozen=True)
class SuggestionsCluster:
    suggestions: list[str]
    embeddings: list[list[float]]


# How many embeddings to process at once, when grouping suggestions
EMBEDDINGS_CHUNK_SIZE: int = 1000
# How many times max to re-group singles to increase group count
EMBEDDINGS_CLUSTERING_MAX_RECURSION: int = 3
# How many additional recursions allowed if the tail is too large (loose suggestions)
EMBEDDINGS_CLUSTERING_MAX_TAIL_RECURSION: int = 3
# If the tail is larger than that - try to cluster once more with more loose approach
EMBEDDINGS_CLUSTERING_MAX_TAIL_PERCENTAGE: float = 0.50
# Split embeddings into chunks to speed up clustering
EMBEDDINGS_CLUSTERING_CHUNK_SIZE: int = 1000  # Increasing from default 25
# Expected average distance between embeddings to group them
EMBEDDINGS_CLUSTERING_DISTANCE: float = 0.9  # Lowering from the default 0.95
# How many times to try to group until to stop
EMBEDDINGS_CLUSTERING_ITERATIONS: int = 5
# How many times to try to group when trying to decrease the tail (too large, loose suggestions)
EMBEDDINGS_CLUSTERING_MAX_TAIL_ITERATIONS: int = 1
# Expected minimal number of suggestions per group when grouping embeddings
EXPECTED_SUGGESTIONS_PER_EMBEDDINGS_GROUP: int = 25  # Increasing from default 5
# Max suggestions per group to avoid large loosely-related groups
MAX_SUGGESTIONS_PER_EMBEDDINGS_GROUP: int = 50
# How to decrease the distance between embeddings to group them with each iteration,
# to increase the number of groups and improve the user experience
EMBEDDINGS_CLUSTERING_DISTANCE_DECREASE: float = 0.01


class Clusterizer:
    @classmethod
    def clusterize_suggestions(
        cls,
        embedded_suggestions: list[str],
        embeddings: list[list[float]],
        max_tail_size: int,
        pre_combined_groups: dict[str, RelevantSuggestionsGroup] | None = None,
        iteration: int = 0,
    ) -> tuple[dict[str, RelevantSuggestionsGroup], SuggestionsCluster]:
        """
        Wrapper for clusterizing suggestions, to allow tracking stats
        for clusterization iterations only once, on final iteration.
        """
        # Assuming the input is sorted alphabetically in hope to improve grouping quality
        return cls._clusterize_suggestions(
            embedded_suggestions=embedded_suggestions,
            embeddings=embeddings,
            max_tail_size=max_tail_size,
            pre_combined_groups=pre_combined_groups,
            iteration=iteration,
        )

    @classmethod
    def _clusterize_suggestions(
        cls,
        embedded_suggestions: list[str],
        embeddings: list[list[float]],
        max_tail_size: int,
        pre_combined_groups: dict[str, RelevantSuggestionsGroup] | None,
        iteration: int,
        clustering_distance: float = EMBEDDINGS_CLUSTERING_DISTANCE,
        clustering_iterations: int = EMBEDDINGS_CLUSTERING_ITERATIONS,
    ) -> tuple[dict[str, RelevantSuggestionsGroup], SuggestionsCluster]:
        groups, singles = cls._clusterize_suggestions_iteration(
            embedded_suggestions=embedded_suggestions,
            embeddings=embeddings,
            iteration=iteration,
            clustering_distance=clustering_distance,
            clustering_iterations=clustering_iterations,
        )
        combined_groups: dict[str, RelevantSuggestionsGroup] = {}
        # If pre-combined groups are provided - add them to the combined groups
        if pre_combined_groups:
            groups = [pre_combined_groups, *groups]
        for group_set in groups:
            combined_groups = {**combined_groups, **group_set}
        # Combine the singles in the expected format
        combined_singles = SuggestionsCluster(suggestions=[], embeddings=[])
        for single in singles:
            combined_singles.suggestions.extend(single.suggestions)
            combined_singles.embeddings.extend(single.embeddings)
        # If there are still iterations left - iterate again
        if iteration < EMBEDDINGS_CLUSTERING_MAX_RECURSION:
            return cls._clusterize_suggestions(
                embedded_suggestions=combined_singles.suggestions,
                embeddings=combined_singles.embeddings,
                max_tail_size=max_tail_size,
                pre_combined_groups=combined_groups,
                iteration=iteration + 1,
            )
        # If the iterations exhausted and the tail is acceptable - return the results
        if len(combined_singles.suggestions) <= max_tail_size:
            return combined_groups, combined_singles
        # If the tail is still too large, but no max tail recursions left - return the results anyway
        if iteration >= (EMBEDDINGS_CLUSTERING_MAX_RECURSION + EMBEDDINGS_CLUSTERING_MAX_TAIL_RECURSION):
            return combined_groups, combined_singles
        # If the tail is still too large and there are max tail recursions left -
        # iterate again with the lowest allowed average distance
        max_tail_clustering_distance = round(
            (
                # Calculate the lowest allowed distance
                EMBEDDINGS_CLUSTERING_DISTANCE
                - (
                    # First iteration doesn't count (i-0), so decrease the distance by 1
                    (EMBEDDINGS_CLUSTERING_ITERATIONS - 1) * EMBEDDINGS_CLUSTERING_DISTANCE_DECREASE
                )
            ),
            2,
        )
        return cls._clusterize_suggestions(
            embedded_suggestions=combined_singles.suggestions,
            embeddings=combined_singles.embeddings,
            max_tail_size=max_tail_size,
            pre_combined_groups=combined_groups,
            iteration=iteration + 1,
            clustering_distance=max_tail_clustering_distance,
            clustering_iterations=EMBEDDINGS_CLUSTERING_MAX_TAIL_ITERATIONS,
        )

    @staticmethod
    def sort_relevant_groups(
        relevant_groups: dict[str, RelevantSuggestionsGroup],
    ) -> dict[str, RelevantSuggestionsGroup]:
        # Sort relevant groups by the average distance, keep the groups with the best distance first
        return dict(
            sorted(  # type: ignore
                relevant_groups.items(),
                key=lambda item: item[1].avg_distance,  # type: ignore
                reverse=True,
            )
        )

    @classmethod
    def _clusterize_suggestions_iteration(
        cls,
        embedded_suggestions: list[str],
        embeddings: list[list[float]],
        iteration: int,
        clustering_distance: float,
        clustering_iterations: int,
    ) -> tuple[list[dict[str, RelevantSuggestionsGroup]], list[SuggestionsCluster]]:
        # Split suggestions into smaller groups based on embeddings
        n_clusters = math.ceil(len(embeddings) / EMBEDDINGS_CLUSTERING_CHUNK_SIZE)
        if n_clusters == 1:
            # If it's a single cluster - create it manually
            init_embeddings_clusters = {
                "single_cluster": SuggestionsCluster(suggestions=embedded_suggestions, embeddings=embeddings)
            }
        else:
            init_embeddings_clusters = cls._calculate_embeddings_clusters(
                embedded_suggestions=embedded_suggestions,
                embeddings=embeddings,
                n_clusters=n_clusters,
                minibatch=True,
            )
        return cls._group_multiple_embeddings_clusters(
            init_embeddings_clusters=init_embeddings_clusters,
            iteration=iteration,
            clustering_distance=clustering_distance,
            clustering_iterations=clustering_iterations,
        )

    @classmethod
    def _group_multiple_embeddings_clusters(
        cls,
        init_embeddings_clusters: dict[str, SuggestionsCluster],
        iteration: int,
        clustering_distance: float,
        clustering_iterations: int,
    ) -> tuple[list[dict[str, RelevantSuggestionsGroup]], list[SuggestionsCluster]]:
        groups = []
        singles = []
        # Find groups of suggestions in each cluster, one by one
        for _i, (_, cluster) in enumerate(
            tqdm(
                init_embeddings_clusters.items(),
                desc=f"Grouping embeddings clusters (iteration: {iteration})",
            )
        ):
            cluster_groups, cluster_singles = cls._group_embeddings_cluster(
                embedded_suggestions=cluster.suggestions,
                embeddings=cluster.embeddings,
                clustering_distance=clustering_distance,
                clustering_iterations=clustering_iterations,
            )
            groups.append(cluster_groups)
            singles.append(cluster_singles)
        return groups, singles

    @classmethod
    def _group_embeddings_cluster(
        cls,
        embedded_suggestions: list[str],
        embeddings: list[list[float]],
        clustering_distance: float,
        clustering_iterations: int,
    ) -> tuple[dict[str, RelevantSuggestionsGroup], SuggestionsCluster]:
        # Define result variables to update with each iteration
        result_relevant_groups: dict[str, RelevantSuggestionsGroup] = {}
        result_singles: SuggestionsCluster = SuggestionsCluster(suggestions=[], embeddings=[])
        suggestions_input, embeddings_input = embedded_suggestions, embeddings
        # An expected average of suggestions per group.
        embeddings_per_group = EXPECTED_SUGGESTIONS_PER_EMBEDDINGS_GROUP
        # How many times to clusterize until to stop (to disallow while loop to run forever)
        # Decrease the required distance (- quality) and decrease the cluster size (+ quality) with each iteration
        for distance_iteration in range(clustering_iterations):
            n_clusters = math.ceil(len(suggestions_input) / embeddings_per_group)
            # Decrease required distance to group embeddings with each iteration,
            # to allow more ideas to be grouped and improve the user experience
            avg_distance_threshold = round(
                clustering_distance - (EMBEDDINGS_CLUSTERING_DISTANCE_DECREASE * distance_iteration),
                2,
            )
            (
                relevant_groups,
                result_singles,
            ) = cls._group_embeddings_cluster_iteration(
                embedded_suggestions=suggestions_input,
                embeddings=embeddings_input,
                n_clusters=n_clusters,
                avg_distance_threshold=avg_distance_threshold,
            )
            # Save successfully groupped suggestions
            result_relevant_groups = {**result_relevant_groups, **relevant_groups}
            # If no singles left - nothing to group again, return results
            if not result_singles.suggestions:
                return result_relevant_groups, result_singles
            # If singles left, but less than a single group - don't group them again
            if len(result_singles.suggestions) < embeddings_per_group:
                return result_relevant_groups, result_singles
            # If enough singles left - try to clusterize them again
            suggestions_input, embeddings_input = (
                result_singles.suggestions,
                result_singles.embeddings,
            )
        # Return the final results
        return result_relevant_groups, result_singles

    @staticmethod
    def _calculate_embeddings_clusters(
        embedded_suggestions: list[str],
        embeddings: list[list[float]],
        n_clusters: int,
        minibatch: bool,
    ) -> dict[str, SuggestionsCluster]:
        matrix = np.vstack(embeddings)
        if not minibatch:
            kmeans = KMeans(n_clusters=n_clusters, init="k-means++", n_init=10, random_state=42)
        else:
            kmeans = MiniBatchKMeans(n_clusters=n_clusters, init="k-means++", n_init=10, random_state=42)
        kmeans.fit_predict(matrix)
        labels: list[int] = kmeans.labels_
        # Organize clustered suggestions
        grouped_suggestions: dict[str, SuggestionsCluster] = {}
        # Generate unique label for each clustering calculation
        unique_label = str(uuid.uuid4())
        for suggestion, label, emb in zip(embedded_suggestions, labels, embeddings):
            formatted_label = f"{label}_{unique_label}"
            if formatted_label not in grouped_suggestions:
                grouped_suggestions[formatted_label] = SuggestionsCluster(suggestions=[], embeddings=[])
            grouped_suggestions[formatted_label].suggestions.append(suggestion)
            grouped_suggestions[formatted_label].embeddings.append(emb)
        return grouped_suggestions

    @classmethod
    def _group_embeddings_cluster_iteration(
        cls,
        embedded_suggestions: list[str],
        embeddings: list[list[float]],
        n_clusters: int,
        avg_distance_threshold: float | None,
    ) -> tuple[dict[str, RelevantSuggestionsGroup], SuggestionsCluster]:
        embeddings_clusters = cls._calculate_embeddings_clusters(
            embedded_suggestions=embedded_suggestions,
            embeddings=embeddings,
            n_clusters=n_clusters,
            minibatch=False,
        )
        # Split into relevant groups and singles
        relevant_groups: dict[str, RelevantSuggestionsGroup] = {}
        singles = SuggestionsCluster(suggestions=[], embeddings=[])
        for group_label, cluster in embeddings_clusters.items():
            if len(cluster.suggestions) <= 1:
                # Groups with a single idea move to singles automatically
                singles.suggestions.extend(cluster.suggestions)
                singles.embeddings.extend(cluster.embeddings)
                continue
            # If avg distance threshold not provided (init chunking) - don't filter groups
            if not avg_distance_threshold:
                # Keep the proper-sized groups that are close to each other
                relevant_groups[group_label] = RelevantSuggestionsGroup(
                    suggestions=cluster.suggestions,
                    avg_distance=None,
                )
                continue
            # Calculate average distance between all suggestions in the group
            distances = []
            for suggestion, emb in zip(cluster.suggestions, cluster.embeddings):
                for l_suggestion, l_emb in zip(cluster.suggestions, cluster.embeddings):
                    if suggestion != l_suggestion:
                        distances.append(_cosine_similarity(emb, l_emb))
            # Round to 2 symbols after the dot
            if not distances:
                # TODO: Remove after testing
                logger.info("")
            avg_distance = round(sum(distances) / len(distances), 2)
            # Groups that aren't close enough move to singles
            if avg_distance < avg_distance_threshold:
                singles.suggestions.extend(cluster.suggestions)
                singles.embeddings.extend(cluster.embeddings)
                continue
            # Avoid having large loosely-connected groups
            if len(cluster.suggestions) > MAX_SUGGESTIONS_PER_EMBEDDINGS_GROUP:
                singles.suggestions.extend(cluster.suggestions)
                singles.embeddings.extend(cluster.embeddings)
                continue
            # Keep the proper-sized groups that are close to each other
            relevant_groups[group_label] = RelevantSuggestionsGroup(
                # Don't save embeddings, as the group is already relevant,
                # so won't go through the clusterization again
                suggestions=cluster.suggestions,
                avg_distance=avg_distance,
            )
        return relevant_groups, singles


if __name__ == "__main__":
    stringified_traces_dir_path = Path("/Users/woutut/Documents/Code/posthog/playground/traces-summarization/output/")
    # Iterate over directories in stringified_traces_dir_path
    traces_dirs = list(stringified_traces_dir_path.iterdir())
    # Preparing the data, while keeping the order, to be able to match summaries with their embeddings
    input_embedded_suggestions: list[str] = []
    input_embeddings: list[list[float]] = []
    # Generate summaries for stringified traces
    for dir_path in traces_dirs:
        if not dir_path.is_dir():
            continue
        trace_id = dir_path.name
        # Get stringified trace summary
        summary_file_name = f"{trace_id}_summary.txt"
        summary_file_path = dir_path / summary_file_name
        if not summary_file_path.exists():
            raise ValueError(f"Summary file ({summary_file_path}) not found for trace {trace_id}")
        with open(summary_file_path) as f:
            summary = f.read()
        # Skip summaries without issues
        if summary.strip(".").strip(" ").lower() == "no issues found":
            continue
        # Get summary embeddings
        summary_embeddings_file_path = dir_path / f"{trace_id}_summary_embeddings.npy"
        if not summary_embeddings_file_path.exists():
            raise ValueError(f"Summary embeddings file ({summary_embeddings_file_path}) not found for trace {trace_id}")
        # Check that it's not empty
        with open(summary_embeddings_file_path, "rb") as f:
            summary_embeddings_np = np.load(f, allow_pickle=True)
        if not summary_embeddings_np.size:
            raise ValueError(f"Summary embeddings file ({summary_embeddings_file_path}) is empty for trace {trace_id}")
        # Convert back into list of embeddings
        summary_embeddings: list[list[float]] = summary_embeddings_np.tolist()
        input_embedded_suggestions.append(summary)
        input_embeddings.append(summary_embeddings[0])  # Each npy file includes embeddings for a single summary only
    logger.info(f"Input embedded suggestions count: {len(input_embedded_suggestions)}")
    logger.info(f"Input embeddings count: {len(input_embeddings)}")
    # Clusterize suggestions
    groups, singles = Clusterizer.clusterize_suggestions(
        embedded_suggestions=input_embedded_suggestions,
        embeddings=input_embeddings,
        max_tail_size=int(len(input_embeddings) * EMBEDDINGS_CLUSTERING_MAX_TAIL_PERCENTAGE),
    )
    # TODO: Remove after testing
    logger.info("")
