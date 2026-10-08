from posthog.settings.utils import get_from_env

# Wall-clock budgets for the two boot health checks. Together they bound how long
# a lifecycle task can occupy a Celery worker on a sandbox that never comes up.
# Environment-overridable because the floor depends on the sandbox provider: a
# cold Modal worker reaches the first probe much later than a local container.
STREAMLIT_AUTH_PROXY_HEALTH_DEADLINE_SECONDS = get_from_env(
    "STREAMLIT_AUTH_PROXY_HEALTH_DEADLINE_SECONDS", 60, type_cast=int
)
STREAMLIT_HEALTH_DEADLINE_SECONDS = get_from_env("STREAMLIT_HEALTH_DEADLINE_SECONDS", 120, type_cast=int)

# Per-command budget for the short shell commands that set the sandbox up. The
# first exec in a new sandbox pays container start-up on top of the command
# itself, and none of these commands is retried.
STREAMLIT_SANDBOX_SETUP_COMMAND_TIMEOUT_SECONDS = get_from_env(
    "STREAMLIT_SANDBOX_SETUP_COMMAND_TIMEOUT_SECONDS", 30, type_cast=int
)
