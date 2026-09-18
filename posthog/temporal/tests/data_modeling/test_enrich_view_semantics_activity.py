from uuid import uuid4

import pytest
import unittest.mock

from django.db import InterfaceError, OperationalError

from temporalio.testing import ActivityEnvironment

from posthog.temporal.data_modeling.activities import enrich_view_semantics as activity_module
from posthog.temporal.data_modeling.activities.enrich_view_semantics import (
    EnrichViewSemanticsInputs,
    enrich_view_semantics_activity,
)

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "error,reported",
    [
        (OperationalError("server closed the connection unexpectedly"), False),
        (InterfaceError("connection already closed"), True),
        (ValueError("boom"), True),
    ],
)
async def test_activity_reports_only_non_transient_failures(error: Exception, reported: bool) -> None:
    # The first read of enrich_view_semantics_sync resolves the Team through a connection pooler, so a
    # pooler recycle surfaces as an OperationalError the activity interceptor (posthog_client.py) already
    # keeps out of error tracking. It only gets that say for an exception nothing reported first, so the
    # activity must apply the same classifier instead of capturing every exception. A dropped connection
    # nobody can act on mints a fresh issue otherwise. The activity must still fail, so Temporal retries.
    with (
        unittest.mock.patch.object(activity_module, "enrich_view_semantics_sync", side_effect=error),
        unittest.mock.patch.object(activity_module, "capture_exception") as mock_capture,
    ):
        inputs = EnrichViewSemanticsInputs(team_id=1, saved_query_id=str(uuid4()))
        with pytest.raises(type(error)):
            await ActivityEnvironment().run(enrich_view_semantics_activity, inputs)

    assert mock_capture.called is reported
