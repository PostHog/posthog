"""Who can use Cloud Agents. Kept free of the product's models, so that core code can import it."""

import posthoganalytics

from posthog.exceptions_capture import capture_exception

FEATURE_FLAG_KEY = "cloud-agents"


def cloud_agents_enabled(distinct_id: str, organization_id: str) -> bool:
    try:
        enabled = posthoganalytics.feature_enabled(
            FEATURE_FLAG_KEY,
            distinct_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception as error:
        capture_exception(error)
        return False
    return bool(enabled)
