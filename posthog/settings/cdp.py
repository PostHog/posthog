from posthog.settings.utils import get_from_env
from posthog.settings.base_variables import DEBUG


CDP_FUNCTION_EXECUTOR_API_URL = get_from_env("CDP_FUNCTION_EXECUTOR_API_URL", "")

if not CDP_FUNCTION_EXECUTOR_API_URL:
    CDP_FUNCTION_EXECUTOR_API_URL = (
        "http://localhost:6738" if DEBUG else "http://ingestion-cdp-function-callbacks.posthog.svc.cluster.local"
    )
