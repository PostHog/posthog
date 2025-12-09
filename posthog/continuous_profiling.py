import logging

import pyroscope

from posthog.settings.continuous_profiling import (
    CONTINUOUS_PROFILING_ENABLED,
    PYROSCOPE_APPLICATION_NAME,
    PYROSCOPE_SAMPLE_RATE,
    PYROSCOPE_SERVER_ADDRESS,
)

logger = logging.getLogger(__name__)


def start_continuous_profiling() -> None:
    """
    Start Pyroscope continuous profiling if enabled.

    Call this early in your application startup to capture the full application profile.

    Environment variables:
        CONTINUOUS_PROFILING_ENABLED: Set to "true" to enable profiling
        PYROSCOPE_SERVER_ADDRESS: Pyroscope server URL (e.g., "http://pyroscope:4040")
        PYROSCOPE_APPLICATION_NAME: Application name to report to Pyroscope
        PYROSCOPE_SAMPLE_RATE: Sampling rate in Hz (default: 100)
    """
    if not CONTINUOUS_PROFILING_ENABLED:
        logger.info("Continuous profiling is disabled")
        return

    if not PYROSCOPE_SERVER_ADDRESS:
        logger.warning("Continuous profiling is enabled but PYROSCOPE_SERVER_ADDRESS is empty, skipping")
        return

    pyroscope.configure(
        application_name=PYROSCOPE_APPLICATION_NAME,
        server_address=PYROSCOPE_SERVER_ADDRESS,
        sample_rate=PYROSCOPE_SAMPLE_RATE,
    )
    logger.info(
        "Continuous profiling started",
        extra={
            "server_address": PYROSCOPE_SERVER_ADDRESS,
            "application_name": PYROSCOPE_APPLICATION_NAME,
            "sample_rate": PYROSCOPE_SAMPLE_RATE,
        },
    )
