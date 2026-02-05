"""Configuration constants for video segment clustering workflow."""

from datetime import timedelta

# What period to consider in clustering run, and how often to run it on schedule
DEFAULT_LOOKBACK_WINDOW = timedelta(days=7)
PROACTIVE_TASKS_SCHEDULE_INTERVAL = timedelta(hours=1)

# Minimum segments required for clustering
# Below this threshold, segments are accumulated for the next run
MIN_SEGMENTS_FOR_CLUSTERING = 3

# Clustering algorithm selection
# Below this threshold, use agglomerative clustering (better for small n, builds clusters bottom-up)
# Above this threshold, use iterative K-means (better for large n, more scalable)
AGGLOMERATIVE_CLUSTERING_SEGMENT_THRESHOLD = 200

# Treatment of noise
# Below this threshold, noise segments are converted to single-segment clusters for actionability analysis
# Above this threshold, noise segments are kept as noise (for high-volume teams, outliers end up noise)
NOISE_DISCARDING_SEGMENT_THRESHOLD = 1000

# Iterative K-means clustering parameters
KMEANS_DISTANCE_THRESHOLD = 0.4  # Max cosine distance to centroid for a cluster to be "tight"
KMEANS_MAX_ITERATIONS = 10  # Maximum number of clustering iterations
MIN_CLUSTER_SIZE = 2  # Minimum segments to attempt clustering
KMEANS_K_MULTIPLIER = 50.0  # Multiplier for log10(n) to estimate K, e.g. 1000 segments in iteration -> log10(1000)*KMEANS_K_MULTIPLIER clusters

# Task matching threshold (for deduplication). Cosine distance - lower = more strict matching
TASK_MATCH_THRESHOLD = 0.3

# Cluster labeling configuration
DEFAULT_SEGMENT_SAMPLES_PER_CLUSTER_FOR_LABELING = 5
LABELING_LLM_MODEL = "gemini-3-flash-preview"
