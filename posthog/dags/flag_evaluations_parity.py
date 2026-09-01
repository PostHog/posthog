from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import dagster
import pydantic
import dagster_slack
from clickhouse_driver import Client

from posthog import settings
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners, settings_with_log_comment, skip_if_already_running
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_SOURCE_EVENT, FLAG_EVALUATIONS_TABLE

FLAG_EVALUATIONS_SLACK_CHANNEL = "#alerts-ingestion"

JOB_NAME = "flag_evaluations_parity"


class FlagEvaluationsParityConfig(dagster.Config):
    """Configuration for the flag_evaluations parity check."""

    enabled_team_lookback_days: int = pydantic.Field(
        default=7,
        description=(
            "How far back to look for teams with flag_evaluations rows. A team enabled at any "
            "point in this window is checked, so a day where the fork wrote nothing at all "
            "reads as a total deficit rather than as the team not being enabled."
        ),
    )
    teams_per_query: int = pydantic.Field(
        default=20,
        description=(
            "Teams compared per query. The comparison groups by uuid, so its memory scales with "
            "the rows in the batch, not with the team count. Lower this if a batch containing a "
            "high-volume team runs out of memory."
        ),
    )
    max_teams: int = pydantic.Field(
        default=500,
        description=(
            "Cap on teams checked in one run, highest volume first. Reaching it is reported, "
            "never silent, because a truncated run otherwise reads as full coverage."
        ),
    )
    target_day: str | None = pydantic.Field(
        default=None,
        description=(
            "Day to check as YYYY-MM-DD. Defaults to yesterday (UTC). Set it on a manual run to "
            "re-check the day a past alert named."
        ),
    )


@dataclass(frozen=True)
class TeamParity:
    team_id: int
    only_in_events: int
    only_in_flag_evaluations: int
    in_both: int


@dataclass(frozen=True)
class ParityResults:
    day: date
    checked: list[TeamParity]
    teams_enabled: int
    teams_truncated: int


def _target_day() -> date:
    return (datetime.now(tz=UTC) - timedelta(days=1)).date()


def _resolve_target_day(target_day: str | None) -> date:
    """The day to check: an explicit YYYY-MM-DD override, else yesterday (UTC)."""
    return date.fromisoformat(target_day) if target_day else _target_day()


@dagster.op
def measure_flag_evaluations_parity(
    context: dagster.OpExecutionContext,
    config: FlagEvaluationsParityConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> ParityResults:
    """Compare flag_evaluations against events for every team the fork is writing for.

    The produce-side counters answer "did we hand the row to Kafka", which is not the
    question. Everything past the ack -- the Kafka engine table, the MV, the writable
    Distributed, the shard -- is unobserved, and kafka_flag_evaluations sets
    kafka_skip_broken_messages, so a malformed row is discarded after a successful produce.
    Only comparing the two tables catches that.
    """

    day = _resolve_target_day(config.target_day)

    def run_queries(client: Client) -> ParityResults:
        query_settings = settings_with_log_comment(context)

        # The enabled set comes from the data rather than from a mirror of the charts
        # allowlist, so the two cannot drift.
        enabled_rows = client.execute(
            f"""
            SELECT team_id, count() AS rows, min(toDate(timestamp)) AS first_day
            FROM {settings.CLICKHOUSE_DATABASE}.{FLAG_EVALUATIONS_TABLE}
            WHERE toDate(timestamp) >= %(lookback_start)s AND toDate(timestamp) <= %(day)s
            GROUP BY team_id
            ORDER BY rows DESC
            """,
            {"lookback_start": day - timedelta(days=config.enabled_team_lookback_days), "day": day},
            settings=query_settings,
        )

        # A team whose earliest row in the lookback window falls on the checked day was
        # switched on that day. Its events from before the allowlist reached the pods have
        # no fork row, so comparing it would report a deficit for a fork that works. Skip it;
        # its first full day is checked on the next run.
        ranked_teams = [int(row[0]) for row in enabled_rows if row[2] < day]
        skipped_activation = len(enabled_rows) - len(ranked_teams)
        teams = ranked_teams[: config.max_teams]
        truncated = len(ranked_teams) - len(teams)
        context.log.info(
            f"{len(ranked_teams)} teams enabled, checking {len(teams)} for {day}"
            + (f", skipped {skipped_activation} activated that day" if skipped_activation else "")
        )

        # The shared cluster resource disables both ceilings (max_execution_time and
        # max_memory_usage are "0"), so this comparison must cap itself: it runs on the
        # cluster that serves customer queries and its group-by state grows with the
        # $feature_flag_called uuids of the largest teams for a whole day. A per-query memory
        # breach reports "for query", which the retry policy leaves alone -- unlike a total
        # server breach or a socket timeout, which it retries up to 8 times -- so a heavy
        # batch fails once instead of repeating at full cost. distributed_aggregation_memory_efficient
        # streams each shard's (team_id, uuid) states rather than merging them all in the
        # initiator. The ceilings are generous guardrails for a batch of teams_per_query
        # teams; lower teams_per_query if a batch reaches them.
        comparison_settings = {
            **query_settings,
            "max_execution_time": "600",
            "max_memory_usage": str(100 * 1024**3),
            "distributed_aggregation_memory_efficient": "1",
        }

        checked: list[TeamParity] = []
        for start in range(0, len(teams), config.teams_per_query):
            batch = teams[start : start + config.teams_per_query]
            rows = client.execute(
                f"""
                SELECT
                    team_id,
                    countIf(in_ev > 0 AND in_fe = 0) AS only_in_events,
                    countIf(in_fe > 0 AND in_ev = 0) AS only_in_flag_evaluations,
                    countIf(in_fe > 0 AND in_ev > 0) AS in_both
                FROM (
                    SELECT team_id, uuid, max(is_fe) AS in_fe, max(is_ev) AS in_ev
                    FROM (
                        SELECT team_id, uuid, 1 AS is_fe, 0 AS is_ev
                        FROM {settings.CLICKHOUSE_DATABASE}.{FLAG_EVALUATIONS_TABLE}
                        WHERE team_id IN %(teams)s AND toDate(timestamp) = %(day)s

                        UNION ALL

                        SELECT team_id, uuid, 0 AS is_fe, 1 AS is_ev
                        FROM {settings.CLICKHOUSE_DATABASE}.events
                        WHERE team_id IN %(teams)s AND toDate(timestamp) = %(day)s
                          AND event = %(event)s
                          -- The fork writes a row only when $feature_flag is a non-empty string,
                          -- and lets every other $feature_flag_called event continue to the events
                          -- table untouched. Without the same condition here, each one reads as a
                          -- lost row. JSONExtractString on its own is not that condition, because
                          -- it renders a number, boolean, object or array as its text, so
                          -- JSONType has to reject those types before the empty-string check.
                          AND JSONType(properties, '$feature_flag') = 'String'
                          AND JSONExtractString(properties, '$feature_flag') != ''
                    )
                    GROUP BY team_id, uuid
                )
                GROUP BY team_id
                """,
                {"teams": batch, "day": day, "event": FLAG_EVALUATIONS_SOURCE_EVENT},
                settings=comparison_settings,
            )
            checked.extend(
                TeamParity(
                    team_id=int(row[0]),
                    only_in_events=int(row[1]),
                    only_in_flag_evaluations=int(row[2]),
                    in_both=int(row[3]),
                )
                for row in rows
            )

        return ParityResults(
            day=day,
            checked=checked,
            teams_enabled=len(ranked_teams),
            teams_truncated=truncated,
        )

    return cluster.any_host(run_queries).result()


def parity_alert_lines(results: ParityResults) -> list[str] | None:
    """The Slack message for a run, or None when there is nothing to say.

    Only a deficit and an uncovered team are worth waking someone for. Excess is reported as
    context but never triggers the alert on its own. It counts uuids the fork wrote that the
    events table has no row for. Over the week to 2026-08-31 in prod-US it stayed at or below
    0.09 percent of the uuids the fork wrote, and was zero on four of the seven days. Re-sent
    uuids are not what it counts: the comparison groups by (team_id, uuid), so the duplicate
    rows that flag_evaluations keeps and the ReplacingMergeTree behind events collapses fold
    into one entry per side before anything is counted, and a re-sent uuid that reached both
    tables lands in in_both.

    There is no threshold on the deficit for the opposite reason: it has measured zero on
    every day checked so far, so any non-zero value is a regression a threshold would hide.
    """

    # No enabled team means the fork wrote nothing anywhere for the whole lookback window, which
    # a rolled-back allowlist produces. Staying quiet here would report it as a clean run.
    if not results.teams_enabled:
        return [
            f"*flag_evaluations parity* for `{results.day}`",
            "No team wrote a flag_evaluations row in the lookback window, so nothing was compared.",
        ]

    deficits = sorted(
        (team for team in results.checked if team.only_in_events > 0),
        key=lambda team: team.only_in_events,
        reverse=True,
    )
    if not deficits and not results.teams_truncated:
        return None

    # A team the query covered but that had no rows on the day emits no result row, so
    # len(checked) counts only teams with rows. Report the queried count so this does not
    # understate coverage or contradict the truncation line below.
    queried = results.teams_enabled - results.teams_truncated
    excess_total = sum(team.only_in_flag_evaluations for team in results.checked)
    lines = [
        f"*flag_evaluations parity* for `{results.day}`",
        f"Checked {queried} of {results.teams_enabled} enabled teams "
        f"({len(results.checked)} had rows on the day). Excess rows: {excess_total:,}.",
    ]
    if results.teams_truncated:
        lines.append(f"{results.teams_truncated} enabled teams were not checked; raise `max_teams`.")
    lines.extend(
        f"Team `{team.team_id}`: {team.only_in_events:,} rows in events with no flag_evaluations row"
        for team in deficits[:10]
    )
    if len(deficits) > 10:
        lines.append(f"…and {len(deficits) - 10} more teams with a deficit")
    return lines


@dagster.op
def report_flag_evaluations_parity(
    context: dagster.OpExecutionContext,
    results: ParityResults,
    slack: dagster.ResourceParam[dagster_slack.SlackResource],
) -> None:
    """Post the parity result to Slack when it needs attention."""

    context.add_output_metadata(
        {
            "day": str(results.day),
            "teams_checked": results.teams_enabled - results.teams_truncated,
            "teams_with_rows": len(results.checked),
            "teams_enabled": results.teams_enabled,
            "deficit_rows": sum(team.only_in_events for team in results.checked),
            "excess_rows": sum(team.only_in_flag_evaluations for team in results.checked),
        }
    )

    lines = parity_alert_lines(results)
    if lines is None:
        context.log.info(f"Parity holds for {len(results.checked)} teams on {results.day}")
        return

    # A Slack failure is logged and swallowed below, and the per-team deficit lines exist
    # nowhere else, so record them before the post is attempted.
    context.log.warning("\n".join(lines))

    if not settings.CLOUD_DEPLOYMENT:
        context.log.info("Skipping Slack notification in non-prod environment")
        return

    # Both regions post to the same channel and team ids are per-region, so the alert
    # must name the deployment that lost the rows.
    lines.append(f"Environment: {settings.CLOUD_DEPLOYMENT}")

    # text is the notification and accessibility fallback, and what Slack shows if it rejects
    # the rich blocks. It carries the same lines, so the truncation clause survives that reject.
    message = "\n".join(lines)
    try:
        slack.get_client().chat_postMessage(
            channel=FLAG_EVALUATIONS_SLACK_CHANNEL,
            text=message,
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": message}}],
        )
    except Exception as e:
        context.log.exception(f"Failed to send Slack notification: {e}")


@dagster.job(tags={"owner": JobOwners.TEAM_INGESTION.value})
def flag_evaluations_parity():
    """Check that every row the flag-evaluations fork wrote also reached the events table."""
    report_flag_evaluations_parity(measure_flag_evaluations_parity())


@dagster.schedule(
    job=flag_evaluations_parity,
    # After the previous UTC day is complete and its merges have settled.
    cron_schedule="0 4 * * *",
    execution_timezone="UTC",
    name="flag_evaluations_parity_schedule",
)
@skip_if_already_running
def flag_evaluations_parity_schedule(context: dagster.ScheduleEvaluationContext) -> dagster.RunRequest:
    # Skip while a previous run is still active so catch-up ticks after an outage do not run
    # several comparisons at once against the shared events cluster and post duplicate alerts
    # for the same day.
    return dagster.RunRequest()
