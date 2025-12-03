import math
from collections import Counter
from statistics import mean

from posthog.schema import (
    DetectorType,
    KMeansAnomalyMethod,
    KMeansDetectorConfig,
    KMeansFeature,
)
from posthog.tasks.alerts.detectors.base import BaseDetector, DetectorResult


class KMeansDetector(BaseDetector):
    """
    K-Means clustering based anomaly detector.

    Builds feature vectors from the time series data and uses K-Means clustering
    to identify anomalous points. Points in the smallest cluster or furthest
    from the mean centroid are considered anomalies.

    Feature vector components (configurable):
    - diff_1: First difference (current - previous)
    - lag_n: Values at previous time steps
    - smoothed_n: Moving averages
    """

    detector_type = DetectorType.KMEANS

    def __init__(self, config: KMeansDetectorConfig):
        self.n_clusters: int = config.n_clusters
        self.features: list[KMeansFeature] = config.features
        self.anomaly_method: KMeansAnomalyMethod = config.anomaly_method

    def _get_required_lookback(self) -> int:
        """Calculate how many historical points are needed to build a feature vector."""
        max_lookback = 0

        for feature in self.features:
            match feature:
                case KMeansFeature.DIFF_1:
                    max_lookback = max(max_lookback, 1)
                case KMeansFeature.LAG_1:
                    max_lookback = max(max_lookback, 1)
                case KMeansFeature.LAG_2:
                    max_lookback = max(max_lookback, 2)
                case KMeansFeature.LAG_3:
                    max_lookback = max(max_lookback, 3)
                case KMeansFeature.LAG_4:
                    max_lookback = max(max_lookback, 4)
                case KMeansFeature.LAG_5:
                    max_lookback = max(max_lookback, 5)
                case KMeansFeature.SMOOTHED_3:
                    max_lookback = max(max_lookback, 2)  # Need 2 previous + current
                case KMeansFeature.SMOOTHED_5:
                    max_lookback = max(max_lookback, 4)
                case KMeansFeature.SMOOTHED_7:
                    max_lookback = max(max_lookback, 6)

        return max_lookback

    def _build_feature_vector(self, data: list[float], index: int) -> list[float] | None:
        """Build a feature vector for the point at the given index."""
        if index < self._get_required_lookback():
            return None

        vector = []

        for feature in self.features:
            match feature:
                case KMeansFeature.DIFF_1:
                    vector.append(data[index] - data[index - 1])
                case KMeansFeature.LAG_1:
                    vector.append(data[index - 1])
                case KMeansFeature.LAG_2:
                    vector.append(data[index - 2])
                case KMeansFeature.LAG_3:
                    vector.append(data[index - 3])
                case KMeansFeature.LAG_4:
                    vector.append(data[index - 4])
                case KMeansFeature.LAG_5:
                    vector.append(data[index - 5])
                case KMeansFeature.SMOOTHED_3:
                    vector.append(mean(data[index - 2 : index + 1]))
                case KMeansFeature.SMOOTHED_5:
                    vector.append(mean(data[index - 4 : index + 1]))
                case KMeansFeature.SMOOTHED_7:
                    vector.append(mean(data[index - 6 : index + 1]))

        return vector

    def _euclidean_distance(self, v1: list[float], v2: list[float]) -> float:
        """Calculate Euclidean distance between two vectors."""
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))

    def _kmeans_cluster(
        self,
        feature_vectors: list[list[float]],
        max_iterations: int = 100,
    ) -> tuple[list[int], list[list[float]]]:
        """
        Simple K-Means clustering implementation.

        Returns:
            - labels: Cluster assignment for each point
            - centroids: Final centroid positions
        """
        if not feature_vectors or len(feature_vectors) < self.n_clusters:
            return [], []

        n_features = len(feature_vectors[0])
        n_points = len(feature_vectors)

        # Initialize centroids by spreading them across the data range
        step = n_points // self.n_clusters
        centroids = [feature_vectors[i * step].copy() for i in range(self.n_clusters)]

        labels = [0] * n_points

        for _ in range(max_iterations):
            # Assign points to nearest centroid
            new_labels = []
            for vector in feature_vectors:
                distances = [self._euclidean_distance(vector, c) for c in centroids]
                new_labels.append(distances.index(min(distances)))

            # Check for convergence
            if new_labels == labels:
                break
            labels = new_labels

            # Update centroids
            for k in range(self.n_clusters):
                cluster_points = [feature_vectors[i] for i in range(n_points) if labels[i] == k]
                if cluster_points:
                    centroids[k] = [sum(p[j] for p in cluster_points) / len(cluster_points) for j in range(n_features)]

        return labels, centroids

    def _identify_anomaly_cluster(
        self,
        labels: list[int],
        centroids: list[list[float]],
    ) -> int:
        """Identify which cluster should be considered anomalous."""
        if not labels or not centroids:
            return -1

        match self.anomaly_method:
            case KMeansAnomalyMethod.SMALLEST:
                # Find the smallest cluster
                cluster_counts = Counter(labels)
                return min(cluster_counts.keys(), key=lambda k: cluster_counts[k])

            case KMeansAnomalyMethod.FURTHEST:
                # Find cluster furthest from the mean of all centroids
                if len(centroids) < 2:
                    return 0

                mean_centroid = [sum(c[i] for c in centroids) / len(centroids) for i in range(len(centroids[0]))]

                distances = [self._euclidean_distance(c, mean_centroid) for c in centroids]
                return distances.index(max(distances))

            case _:
                return 0

    def evaluate(
        self,
        data: list[float],
        timestamps: list[str],
        series_label: str,
        check_index: int | None = None,
    ) -> DetectorResult:
        min_points = self.get_minimum_data_points()

        if len(data) < min_points:
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message=f"Insufficient data: need at least {min_points} points, have {len(data)}",
            )

        # Default to checking the most recent point
        if check_index is None:
            check_index = -1

        # Resolve negative indices
        actual_index = check_index if check_index >= 0 else len(data) + check_index
        if actual_index < 0 or actual_index >= len(data):
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message=f"Check index {check_index} out of range for data length {len(data)}",
            )

        # Build feature vectors for all valid points
        required_lookback = self._get_required_lookback()
        feature_vectors = []
        valid_indices = []

        for i in range(required_lookback, len(data)):
            vector = self._build_feature_vector(data, i)
            if vector is not None:
                feature_vectors.append(vector)
                valid_indices.append(i)

        if len(feature_vectors) < self.n_clusters:
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message=f"Not enough feature vectors ({len(feature_vectors)}) for {self.n_clusters} clusters",
            )

        # Run K-Means clustering
        labels, centroids = self._kmeans_cluster(feature_vectors)

        if not labels:
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message="K-Means clustering failed",
            )

        # Identify anomaly cluster
        anomaly_cluster = self._identify_anomaly_cluster(labels, centroids)

        # Check if the target point is in the anomaly cluster
        if actual_index not in valid_indices:
            return DetectorResult(
                is_breaching=False,
                breach_indices=[],
                value=None,
                message="Target point doesn't have enough history for feature vector",
            )

        target_label_index = valid_indices.index(actual_index)
        target_cluster = labels[target_label_index]
        is_breaching = target_cluster == anomaly_cluster

        if is_breaching:
            cluster_counts = Counter(labels)
            anomaly_size = cluster_counts[anomaly_cluster]
            return DetectorResult(
                is_breaching=True,
                breach_indices=[actual_index],
                value=float(anomaly_cluster),
                message=f"Value ({series_label}) is in anomaly cluster {anomaly_cluster} (size: {anomaly_size}/{len(labels)} points)",
            )

        return DetectorResult(
            is_breaching=False,
            breach_indices=[],
            value=float(target_cluster),
            message=None,
        )

    def get_breach_points(
        self,
        data: list[float],
        timestamps: list[str],
    ) -> list[int]:
        required_lookback = self._get_required_lookback()

        if len(data) < required_lookback + self.n_clusters:
            return []

        # Build feature vectors for all valid points
        feature_vectors = []
        valid_indices = []

        for i in range(required_lookback, len(data)):
            vector = self._build_feature_vector(data, i)
            if vector is not None:
                feature_vectors.append(vector)
                valid_indices.append(i)

        if len(feature_vectors) < self.n_clusters:
            return []

        # Run K-Means clustering
        labels, centroids = self._kmeans_cluster(feature_vectors)

        if not labels:
            return []

        # Identify anomaly cluster
        anomaly_cluster = self._identify_anomaly_cluster(labels, centroids)

        # Return all points in the anomaly cluster
        breach_indices = [valid_indices[i] for i, label in enumerate(labels) if label == anomaly_cluster]

        return breach_indices

    @classmethod
    def get_minimum_data_points(cls) -> int:
        # Need enough points for feature vectors plus clustering
        # At minimum: lookback + n_clusters (default 3)
        return 10  # Conservative default; actual requirement depends on config
