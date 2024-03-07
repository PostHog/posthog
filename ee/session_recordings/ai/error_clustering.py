from prometheus_client import Histogram
from django.conf import settings
from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
from sklearn.cluster import DBSCAN
import pandas as pd

FIND_RECORDING_NEIGHBOURS_TIMING = Histogram(
    "posthog_session_recordings_find_recording_neighbours",
    "Time spent finding the most similar recording embeddings for a single session",
)

DBSCAN_EPS = settings.REPLAY_EMBEDDINGS_CLUSTERING_DBSCAN_EPS
DBSCAN_MIN_SAMPLES = settings.REPLAY_EMBEDDINGS_CLUSTERING_DBSCAN_MIN_SAMPLES


def error_clustering(team: Team):
    results = fetch_error_embeddings(team.pk)
    cluster_embeddings(results)

    df = pd.DataFrame(results, columns=["session_id", "embeddings"])
    df["cluster"] = cluster_embeddings(results)
    return df.groupby("cluster").sample(n=DBSCAN_MIN_SAMPLES)


def fetch_error_embeddings(team_id: int):
    query = """
            SELECT
                session_id, embeddings
            FROM
                session_replay_embeddings
            WHERE
                team_id = %(team_id)s
                -- don't load all data for all time
                AND generation_timestamp > now() - INTERVAL 7 DAY
                AND source_type = 'error'
        """

    return sync_execute(
        query,
        {"team_id": team_id},
    )


def cluster_embeddings(embeddings):
    dbscan = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES)
    dbscan.fit(embeddings)
    return dbscan.labels_
