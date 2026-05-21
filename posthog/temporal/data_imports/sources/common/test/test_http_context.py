import uuid
import contextvars
from concurrent.futures import ThreadPoolExecutor

import pytest

import structlog

from posthog.temporal.data_imports.sources.common.http import context as ctx_mod
from posthog.temporal.data_imports.sources.common.http.context import (
    JobContext,
    bind_job_context,
    current_job_context,
    scoped_job_context,
)


@pytest.fixture(autouse=True)
def _reset_contextvar():
    token = ctx_mod._current_job_context.set(None)
    structlog.contextvars.clear_contextvars()
    try:
        yield
    finally:
        ctx_mod._current_job_context.reset(token)
        structlog.contextvars.clear_contextvars()


def _make_kwargs(**overrides):
    base = {
        "team_id": 42,
        "source_type": "stripe",
        "external_data_source_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "external_data_schema_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "external_data_job_id": "run-abc",
    }
    base.update(overrides)
    return base


def test_job_context_as_log_fields_returns_all_labels():
    job = JobContext(
        team_id=1,
        source_type="stripe",
        external_data_source_id="src",
        external_data_schema_id="sch",
        external_data_job_id="run",
    )
    assert job.as_log_fields() == {
        "team_id": 1,
        "source_type": "stripe",
        "external_data_source_id": "src",
        "external_data_schema_id": "sch",
        "external_data_job_id": "run",
    }


def test_bind_job_context_sets_contextvar_and_returns_context():
    returned = bind_job_context(**_make_kwargs())

    current = current_job_context()
    assert current is not None
    assert current is returned
    assert current.team_id == 42
    assert current.source_type == "stripe"


def test_bind_job_context_stringifies_uuids():
    job_uuid = uuid.UUID("33333333-3333-3333-3333-333333333333")
    bind_job_context(**_make_kwargs(external_data_source_id=job_uuid, external_data_schema_id=job_uuid))

    current = current_job_context()
    assert current is not None
    assert current.external_data_source_id == str(job_uuid)
    assert current.external_data_schema_id == str(job_uuid)
    assert isinstance(current.external_data_source_id, str)


def test_bind_job_context_binds_structlog_contextvars():
    bind_job_context(**_make_kwargs())

    bound = structlog.contextvars.get_contextvars()
    assert bound["source_type"] == "stripe"
    assert bound["external_data_source_id"] == "11111111-1111-1111-1111-111111111111"
    assert bound["external_data_schema_id"] == "22222222-2222-2222-2222-222222222222"
    assert bound["external_data_job_id"] == "run-abc"


def test_scoped_job_context_resets_on_exit():
    assert current_job_context() is None

    with scoped_job_context(**_make_kwargs()) as inner:
        assert current_job_context() is inner
        bound = structlog.contextvars.get_contextvars()
        assert bound["source_type"] == "stripe"

    assert current_job_context() is None
    bound_after = structlog.contextvars.get_contextvars()
    for field in ("source_type", "external_data_source_id", "external_data_schema_id", "external_data_job_id"):
        assert field not in bound_after


def test_scoped_job_context_resets_on_exception():
    with pytest.raises(RuntimeError):
        with scoped_job_context(**_make_kwargs()):
            assert current_job_context() is not None
            raise RuntimeError("boom")

    assert current_job_context() is None


def test_scoped_job_context_nesting_restores_outer_context():
    with scoped_job_context(**_make_kwargs(team_id=1, source_type="outer")) as outer:
        with scoped_job_context(**_make_kwargs(team_id=2, source_type="inner")) as inner:
            inside = current_job_context()
            assert inside is inner
            assert inside is not None and inside.team_id == 2
        # After inner exits, outer should be restored
        outside = current_job_context()
        assert outside is outer
        assert outside is not None and outside.team_id == 1


def test_context_propagates_across_threadpool_via_copy_context():
    bind_job_context(**_make_kwargs(team_id=999))

    captured: list[JobContext | None] = []

    def task() -> None:
        captured.append(current_job_context())

    with ThreadPoolExecutor(max_workers=1) as pool:
        snapshot = contextvars.copy_context()
        pool.submit(snapshot.run, task).result()

    assert len(captured) == 1
    assert captured[0] is not None
    assert captured[0].team_id == 999


def test_threadpool_without_copy_context_does_not_inherit():
    """Negative control: without copy_context the contextvar resets in a new thread."""
    bind_job_context(**_make_kwargs(team_id=999))

    captured: list[JobContext | None] = []

    def task() -> None:
        captured.append(current_job_context())

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(task).result()

    # Threadpool workers don't automatically inherit contextvars; copy_context() is required.
    # This is a sanity check that confirms the propagation pattern in pipeline.py is doing real work.
    assert captured == [None]
