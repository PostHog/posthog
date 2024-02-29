from prometheus_client import Histogram

from typing import List
from structlog import get_logger
from django.conf import settings

from posthog.clickhouse.client import sync_execute
from posthog.models.team import Team
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn import preprocessing

GENERATE_RECORDING_CLUSTERS_TIMING = Histogram(
    "posthog_session_recordings_generate_cluster_embedding",
    "Time spent generating clusters for a set of recordings",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20],
)

logger = get_logger(__name__)

DBSCAN_EPS = settings.REPLAY_CLUSTERING_DBSCAN_EPS
DBSCAN_MIN_SAMPLE_COUNT = settings.REPLAY_CLUSTERING_MIN_SAMPLE_COUNT
# reusing value from embeddings
MIN_DURATION_INCLUDE_SECONDS = settings.REPLAY_EMBEDDINGS_MIN_DURATION_SECONDS


def cluster_recordings(team: Team):
    preferred_events = fetch_preferred_events(team=team)
    results = generate_input_data(team_id=team.id, preferred_events=preferred_events)

    logger.info(
        f"clustering {len(results.index)} sessions for team {team.pk}", flow="replay_clustering", team_id=team.pk
    )

    with GENERATE_RECORDING_CLUSTERS_TIMING.time():
        results["cluster"] = cluster_sessions(results)
        logger.info(
            f"generated {results['cluster'].nunique()} unique clusters", flow="replay_clustering", team_id=team.pk
        )


def generate_input_data(team_id: int, preferred_events: List[str]):
    events_df = pd.DataFrame(
        fetch_event_counts(team_id=team_id, preferred_events=preferred_events),
        columns=["session_id", "event", "count"],
    )
    event_counts_per_session_df = events_df.pivot_table(
        values="count", index="session_id", columns="event", fill_value=0
    )
    event_counts_per_session_df = event_counts_per_session_df.reset_index()

    replay_summary_df = pd.DataFrame(
        fetch_session_replay_aggregations(team_id=team_id, session_ids=list(event_counts_per_session_df["session_id"])),
        columns=[
            "session_id",
            "duration",
            "click_count",
            "keypress_count",
            "mouse_activity_count",
            "active_seconds",
            "console_log_count",
            "console_warn_count",
            "console_error_count",
        ],
    )

    return replay_summary_df.merge(event_counts_per_session_df, how="inner")


def cluster_sessions(results):
    normalized_results = preprocessing.normalize(results.loc[:, results.columns != "session_id"], norm="l2")
    dbscan = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLE_COUNT)
    dbscan.fit(normalized_results)
    return dbscan.labels_


def fetch_event_counts(team_id: int, preferred_events: List[str]):
    query = """
        SELECT $session_id, event, count(*) as count
        FROM
            events
        WHERE
            timestamp > now() - INTERVAL 7 DAY
            AND timestamp < now() - INTERVAL 1 DAY
            AND team_id = %(team_id)s
            AND event in %(preferred_events)s
            AND $session_id is not null and $session_id != ''
        GROUP BY $session_id, event
    """

    return sync_execute(
        query,
        {"team_id": team_id, "preferred_events": preferred_events},
    )


def fetch_session_replay_aggregations(team_id: int, session_ids: List[str]):
    query = """
        SELECT
            session_id,
            dateDiff('SECOND', min(min_first_timestamp), max(max_last_timestamp)),
            sum(click_count),
            sum(keypress_count),
            sum(mouse_activity_count),
            sum(active_milliseconds)/1000 as active_seconds,
            sum(console_log_count) as console_log_count,
            sum(console_warn_count) as console_warn_count,
            sum(console_error_count) as console_error_count
        FROM
            session_replay_events
        PREWHERE
            team_id = %(team_id)s
            -- must be a completed session
            AND min_first_timestamp < now() - INTERVAL 1 DAY
            -- let's not load all data for all time
            -- will definitely need to do something about this length of time
            AND min_first_timestamp > now() - INTERVAL 7 DAY
            AND session_id in %(session_ids)s
        GROUP BY session_id
        HAVING dateDiff('second', min(min_first_timestamp), max(max_last_timestamp)) > %(min_duration_include_seconds)s
    """

    return sync_execute(
        query,
        {
            "team_id": team_id,
            "session_ids": session_ids,
            "min_duration_include_seconds": MIN_DURATION_INCLUDE_SECONDS,
        },
    )


def fetch_preferred_events(team: Team):
    replay_config = team.session_replay_config or {}
    replay_ai_config = replay_config.get("ai_config", {})
    return replay_ai_config.get("preferred_events", ["$pageview"])
