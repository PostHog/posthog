from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.flag_evaluations_json_parity import compare_counts, flag_evaluations_json_parity_job

WINDOW_DAYS = 3


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


def call_uuid(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, label)


def seed(
    cluster: ClickhouseCluster,
    table: str,
    label: str,
    when: datetime,
    *,
    flag_key: str = "flag-a",
    response: str = "control",
) -> None:
    row = (
        1,
        f"{label}-user",
        uuid5(NAMESPACE_URL, f"{label}-user"),
        call_uuid(label),
        when,
        flag_key,
        response,
        "",
        when,
    )

    def insert(client: Client) -> None:
        client.execute(
            f"""INSERT INTO {table}
            (team_id, distinct_id, person_id, uuid, timestamp, flag_key, response, request_id, _timestamp)
            VALUES""",
            [row],
        )

    cluster.any_host(insert).result()


def seed_legacy(cluster: ClickhouseCluster, label: str, when: datetime, **kwargs: str) -> None:
    seed(cluster, "writable_flag_evaluations", label, when, **kwargs)


def seed_json(cluster: ClickhouseCluster, label: str, when: datetime, **kwargs: str) -> None:
    seed(cluster, "writable_flag_evaluations_json", label, when, **kwargs)


def run_parity(cluster: ClickhouseCluster, now: datetime) -> dagster.ExecuteInProcessResult:
    config = {"config": {"start_date": str((now - timedelta(days=WINDOW_DAYS)).date()), "end_date": str(now.date())}}
    return flag_evaluations_json_parity_job.execute_in_process(
        run_config={"ops": {"compare_flag_evaluations_json_parity": config}},
        resources={"cluster": cluster},
        instance=dagster.DagsterInstance.ephemeral(),
        raise_on_error=False,
    )


def failure_message(result: dagster.ExecuteInProcessResult) -> str:
    [failure] = result.get_step_failure_events()
    assert failure.step_failure_data.error is not None
    return failure.step_failure_data.error.message


def test_compare_counts_lists_each_key_whose_count_differs() -> None:
    legacy = {("a",): 3, ("b",): 2, ("c",): 1}
    new = {("a",): 3, ("b",): 5, ("d",): 4}

    assert compare_counts(legacy, new) == [(("b",), 2, 5), (("c",), 1, 0), (("d",), 0, 4)]


@pytest.mark.django_db
def test_parity_passes_when_both_tables_hold_the_same_calls(cluster: ClickhouseCluster, now: datetime) -> None:
    when = now - timedelta(days=1, hours=6)
    for label in ("one", "two"):
        seed_legacy(cluster, label, when)
        seed_json(cluster, label, when)

    assert run_parity(cluster, now).success


@pytest.mark.django_db
def test_parity_passes_when_a_copied_row_is_inserted_twice_and_not_merged(
    cluster: ClickhouseCluster, now: datetime
) -> None:
    # A Partforge copy and the dual-written Kafka row can both hold the call. Identical rows collapse in a merge,
    # so until then the check must not count them as duplicates.
    when = now - timedelta(days=1, hours=6)
    seed_legacy(cluster, "one", when)
    seed_json(cluster, "one", when)
    seed_json(cluster, "one", when)

    assert run_parity(cluster, now).success


@pytest.mark.django_db
def test_parity_fails_and_names_the_day_when_the_new_table_lacks_a_call(
    cluster: ClickhouseCluster, now: datetime
) -> None:
    when = now - timedelta(days=1, hours=6)
    seed_legacy(cluster, "one", when)

    message = failure_message(run_parity(cluster, now))

    assert str(when.date()) in message
    assert "flag-a" in message


@pytest.mark.django_db
def test_parity_fails_when_a_call_has_another_response_in_the_new_table(
    cluster: ClickhouseCluster, now: datetime
) -> None:
    when = now - timedelta(days=1, hours=6)
    seed_legacy(cluster, "one", when, response="control")
    seed_json(cluster, "one", when, response="test")

    message = failure_message(run_parity(cluster, now))

    assert "control" in message
    assert "test" in message


@pytest.mark.django_db
def test_parity_reports_duplicate_rows_that_the_distinct_counts_hide(cluster: ClickhouseCluster, now: datetime) -> None:
    # The same call at two timestamps has two sort keys, so no merge collapses it. Every distinct count still
    # matches the legacy table.
    when = now - timedelta(days=1, hours=6)
    seed_legacy(cluster, "one", when)
    seed_json(cluster, "one", when)
    seed_json(cluster, "one", when + timedelta(minutes=5))

    message = failure_message(run_parity(cluster, now))

    assert "duplicate" in message
    assert str(when.date()) in message
    assert "differ" not in message
