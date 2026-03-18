import os
import logging

logger = logging.getLogger(__name__)

# K8s metadata environment variables for Pyroscope tags
K8S_TAG_ENV_VARS = {
    "namespace": "K8S_NAMESPACE",
    "pod": "K8S_POD_NAME",
    "node": "K8S_NODE_NAME",
    "pod_template_hash": "K8S_POD_TEMPLATE_HASH",
    "app_instance": "K8S_APP_INSTANCE",
    "app": "K8S_APP",
    "container": "K8S_CONTAINER_NAME",
    "controller_type": "K8S_CONTROLLER_TYPE",
}


def _collect_k8s_tags() -> dict[str, str]:
    """Collect K8s metadata tags from environment variables."""
    tags = {"src": "SDK"}
    for tag_name, env_var in K8S_TAG_ENV_VARS.items():
        value = os.getenv(env_var, "")
        if value:
            tags[tag_name] = value
        else:
            logger.warning("K8s tag %s not set (env var %s is empty)", tag_name, env_var)
    return tags


def start_continuous_profiling() -> None:
    """
    Start Pyroscope continuous profiling if enabled.

    Call this early in your application startup to capture the full application profile.
    This function fails gracefully - it will log warnings/errors but never raise exceptions.

    Environment variables:
        CONTINUOUS_PROFILING_ENABLED: Set to "true" to enable profiling
        PYROSCOPE_SERVER_ADDRESS: Pyroscope server URL (e.g., "http://pyroscope:4040")
        PYROSCOPE_APPLICATION_NAME: Application name to report to Pyroscope
        PYROSCOPE_SAMPLE_RATE: Sampling rate in Hz (default: 100)

    K8s metadata tags (from Downward API or Helm):
        K8S_NAMESPACE, K8S_POD_NAME, K8S_NODE_NAME, K8S_POD_TEMPLATE_HASH,
        K8S_APP_INSTANCE, K8S_APP, K8S_CONTAINER_NAME, K8S_CONTROLLER_TYPE
    """
    try:
        # Read directly from environment to avoid Django settings import issues
        # This module is imported before Django is fully initialized
        enabled = os.getenv("CONTINUOUS_PROFILING_ENABLED", "").lower() in ("true", "1", "yes")
        if not enabled:
            return

        server_address = os.getenv("PYROSCOPE_SERVER_ADDRESS", "")
        if not server_address:
            logger.warning("Continuous profiling is enabled but PYROSCOPE_SERVER_ADDRESS is empty, skipping")
            return

        application_name = os.getenv("PYROSCOPE_APPLICATION_NAME", "")
        sample_rate = int(os.getenv("PYROSCOPE_SAMPLE_RATE", "100"))
        tags = _collect_k8s_tags()

        import pyroscope

        pyroscope.configure(
            application_name=application_name,
            server_address=server_address,
            sample_rate=sample_rate,
            tags=tags,
        )
        logger.info(
            "Continuous profiling started",
            extra={
                "server_address": server_address,
                "application_name": application_name,
                "sample_rate": sample_rate,
                "tags": tags,
            },
        )
    except ImportError:
        logger.warning("pyroscope-io package not installed, continuous profiling unavailable")
    except Exception:
        logger.exception("Failed to start continuous profiling")
