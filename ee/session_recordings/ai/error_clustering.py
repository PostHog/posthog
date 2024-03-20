from prometheus_client import Histogram
from django.conf import settings
from posthog.clickhouse.client import sync_execute
from posthog.models import Team, User
from sklearn.cluster import DBSCAN
import pandas as pd
import numpy as np
from posthog.session_recordings.models.session_recording_event import SessionRecordingViewed

CLUSTER_REPLAY_ERRORS_TIMING = Histogram(
    "posthog_session_recordings_cluster_replay_errors",
    "Time spent clustering the embeddings of replay errors",
    buckets=[0.5, 1, 2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60],
)

CLUSTER_REPLAY_ERRORS_CLUSTER_COUNT = Histogram(
    "posthog_session_recordings_errors_cluster_count",
    "Count of clusters identified from error messages per team",
    buckets=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25, 30, 35, 40, 45, 50],
    labelnames=["team_id"],
)

DBSCAN_EPS = settings.REPLAY_EMBEDDINGS_CLUSTERING_DBSCAN_EPS
DBSCAN_MIN_SAMPLES = settings.REPLAY_EMBEDDINGS_CLUSTERING_DBSCAN_MIN_SAMPLES


def error_clustering(team: Team, user: User):
    results = fetch_error_embeddings(team.pk)

    return [
        {
            "cluster": -1,
            "occurrences": 71356,
            "sample": "this is a sample error",
            "session_ids": ["1234567", "765432", "623452643"],
            "unique_sessions": 1345,
            "viewed": 1,
        },
        {
            "cluster": -1,
            "occurrences": 71356,
            "sample": "this is a sample error",
            "session_ids": ["1234567", "765432", "623452643"],
            "unique_sessions": 1345,
            "viewed": 1,
        },
    ]

    if not results:
        return []

    df = pd.DataFrame(results, columns=["session_id", "input", "embeddings"])

    df["cluster"] = cluster_embeddings(df["embeddings"].tolist())

    CLUSTER_REPLAY_ERRORS_CLUSTER_COUNT.labels(team_id=team.pk).observe(df["cluster"].nunique())

    return construct_response(df, team, user)


def fetch_error_embeddings(team_id: int):
    query = """
            SELECT
                session_id, input, embeddings
            FROM
                session_replay_embeddings
            WHERE
                team_id = %(team_id)s
                -- don't load all data for all time
                AND generation_timestamp > now() - INTERVAL 7 DAY
                AND source_type = 'error'
                AND input != ''
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


def construct_response(df: pd.DataFrame, team: Team, user: User):
    viewed_session_ids = list(
        SessionRecordingViewed.objects.filter(team=team, user=user, session_id__in=df["session_id"].unique())
        .values_list("session_id", flat=True)
        .distinct()
    )

    clusters = []
    for cluster, rows in df.groupby("cluster"):
        session_ids = rows["session_id"].unique()
        sample = rows.sample(n=1)[["session_id", "input"]].rename(columns={"input": "error"}).to_dict("records")[0]
        clusters.append(
            {
                "cluster": cluster,
                "sample": sample.get("error"),
                "session_ids": np.random.choice(session_ids, size=DBSCAN_MIN_SAMPLES - 1),
                "occurrences": rows.size,
                "unique_sessions": len(session_ids),
                "viewed": len(np.intersect1d(session_ids, viewed_session_ids, assume_unique=True)),
            }
        )
    return clusters
