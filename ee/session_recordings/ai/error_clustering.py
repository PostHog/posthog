from prometheus_client import Histogram
from django.conf import settings
from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
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


def error_clustering(team: Team):
    return [
        {
            "cluster": 0,
            "samples": [
                {
                    "session_id": "1234567",
                    "input": '{"error":"TypeError: Failed to fetch\\n    at https://app-static-prod.posthog.com/static/chunk-A7UWEVCN.js:5:359\\n    at https://us-assets.i.posthog.com/static/recorder-v2.js?v=1.111.1:16:27600\\n    at l (https://us-assets.i.posthog.com/static/recorder-v2.js?v=1.111.1:1:1844)\\n    at Generator._invoke (https://us-assets.i.posthog.com/static/recorder-v2.js?v=1.111.1:1:1597)\\n    at Generator.next (https://us-assets.i.posthog.com/static/recorder-v2.js?v=1.111.1:1:2207)\\n    at a (https://us-assets.i.posthog.com/static/recorder-v2.js?v=1.111.1:1:7313)\\n    at s (https://us-assets.i.posthog.com/static/recorder-v2.js?v=1.111.1:1:7516)\\nEnd of stack for Error object","reducerKey":"response","actionKey":"loadNewData"}',
                },
                {"session_id": "998765432", "input": "fdgbvafvfd"},
            ],
            "occurrences": 100,
            "unique_sessions": 2,
            "viewed": 4,
        },
        {
            "cluster": 1,
            "samples": [
                {"session_id": "1234567", "input": "sdfghfds"},
                {"session_id": "998765432", "input": "fdgbvafvfd"},
            ],
            "occurrences": 234567,
            "unique_sessions": 10,
            "viewed": 5,
        },
        {
            "cluster": 2,
            "samples": [
                {"session_id": "1234567", "input": "sdfghfds"},
                {"session_id": "998765432", "input": "fdgbvafvfd"},
            ],
            "occurrences": 10,
            "unique_sessions": 5,
            "viewed": 8,
        },
    ]

    results = fetch_error_embeddings(team.pk)

    if not results:
        return []

    df = pd.DataFrame(results, columns=["session_id", "input", "embeddings"])

    df["cluster"] = cluster_embeddings(df["embeddings"].tolist())

    CLUSTER_REPLAY_ERRORS_CLUSTER_COUNT.labels(team_id=team.pk).observe(df["cluster"].nunique())

    return construct_response(df, team)


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


def construct_response(df, team):
    sessions_viewed = (
        SessionRecordingViewed.objects.filter(team=team, session_id__in=df["session_id"].unique())
        .values_list("session_id", flat=True)
        .distinct()
    )

    return [
        {
            "cluster": cluster,
            "samples": rows.head(n=DBSCAN_MIN_SAMPLES)[["session_id", "input"]].to_dict("records"),
            "occurrences": rows.size,
            "unique_sessions": rows["session_id"].nunique(),
            "viewed": len(np.intersect1d(rows["session_id"].unique(), sessions_viewed, assume_unique=True)),
        }
        for cluster, rows in df.groupby("cluster")
    ]
