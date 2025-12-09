import os
import logging

logger = logging.getLogger(__name__)


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

        import pyroscope

        pyroscope.configure(
            application_name=application_name,
            server_address=server_address,
            sample_rate=sample_rate,
        )
        logger.info(
            "Continuous profiling started",
            extra={
                "server_address": server_address,
                "application_name": application_name,
                "sample_rate": sample_rate,
            },
        )
    except ImportError:
        logger.warning("pyroscope-io package not installed, continuous profiling unavailable")
    except Exception:
        logger.exception("Failed to start continuous profiling")
