from prometheus_client import Histogram
from django.conf import settings
from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
from sklearn.cluster import DBSCAN
import pandas as pd

CLUSTER_REPLAY_ERRORS_TIMING = Histogram(
    "posthog_session_recordings_cluster_replay_errors",
    "Time spent clustering the embeddings of replay errors",
    buckets=[0.5, 1, 2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60],
)

DBSCAN_EPS = settings.REPLAY_EMBEDDINGS_CLUSTERING_DBSCAN_EPS
DBSCAN_MIN_SAMPLES = settings.REPLAY_EMBEDDINGS_CLUSTERING_DBSCAN_MIN_SAMPLES


def error_clustering(team: Team):
    results = fetch_error_embeddings(team.pk)

    if not results:
        return []

    cluster_embeddings(results)

    df = pd.DataFrame(results, columns=["session_id", "embeddings"])
    df["cluster"] = cluster_embeddings(results)
    return construct_response(df)


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
    with CLUSTER_REPLAY_ERRORS_TIMING.time():
        dbscan.fit(embeddings)
    return dbscan.labels_


def construct_response(df):
    return [
        {
            "cluster": cluster,
            "samples": rows.sample(n=DBSCAN_MIN_SAMPLES)[["session_id", "message"]].to_dict("records"),
            "occurrences": rows.size,
            "unique_sessions": rows["session_id"].count(),
        }
        for cluster, rows in df.groupby("cluster")
    ]
