import pytest

from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON, Decision, Sampler
from opentelemetry.util.types import Attributes

from posthog.temporal.common.open_telemetry import WorkflowIdPrefixSampler

BATCH_EXPORT_ID = "0195b0c9-4baf-7000-8000-000000000000"


@pytest.mark.parametrize(
    "attributes,delegate,expected_decision",
    [
        # Matching workflow IDs are always sampled, even when the delegate would drop them.
        ({"temporalWorkflowID": f"{BATCH_EXPORT_ID}-2026-07-08T00:00:00Z"}, ALWAYS_OFF, Decision.RECORD_AND_SAMPLE),
        ({"temporalWorkflowID": f"{BATCH_EXPORT_ID}-Backfill-START-END"}, ALWAYS_OFF, Decision.RECORD_AND_SAMPLE),
        # Everything else follows the delegate's decision.
        ({"temporalWorkflowID": "some-other-workflow-id"}, ALWAYS_OFF, Decision.DROP),
        ({"temporalWorkflowID": "some-other-workflow-id"}, ALWAYS_ON, Decision.RECORD_AND_SAMPLE),
        ({}, ALWAYS_OFF, Decision.DROP),
        (None, ALWAYS_OFF, Decision.DROP),
        ({"temporalWorkflowID": 123}, ALWAYS_OFF, Decision.DROP),
    ],
)
def test_workflow_id_prefix_sampler(attributes: Attributes, delegate: Sampler, expected_decision: Decision) -> None:
    sampler = WorkflowIdPrefixSampler([BATCH_EXPORT_ID, "another-prefix"], delegate=delegate)

    result = sampler.should_sample(None, trace_id=1, name="RunWorkflow:s3-export", attributes=attributes)

    assert result.decision == expected_decision
