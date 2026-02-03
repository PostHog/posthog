"""
PostHog Analytics configuration for Temporal workers.

This module configures the posthoganalytics SDK to be safe for use in Temporal workers,
which are highly concurrent environments with multiple threads (Consumer threads, Poller
thread, activity executor threads, etc.).

Usage:
    Call `configure_posthog_analytics_for_temporal()` early in Temporal worker startup,
    before any posthoganalytics calls are made.
"""

import structlog

logger = structlog.get_logger(__name__)


def configure_posthog_analytics_for_temporal() -> None:
    """
    Configure posthoganalytics for safe use in Temporal workers.

    This must be called early in worker startup, before any posthoganalytics
    operations occur. It applies settings that avoid thread-safety issues
    in the SDK's connection pool management.
    """
    import posthoganalytics

    # Disable connection pooling to avoid corrupted pool state from concurrent access.
    # This forces fresh HTTP connections per request, which has slightly higher overhead
    # but avoids the race conditions in the global session management.
    try:
        posthoganalytics.disable_connection_reuse()
        logger.info("posthog_analytics_config", action="disabled_connection_reuse")
    except AttributeError:
        # Older versions of posthoganalytics don't have this function
        logger.warning(
            "posthog_analytics_config",
            action="disable_connection_reuse_not_available",
            message="posthoganalytics.disable_connection_reuse() not available, skipping",
        )

    # Disable local evaluation by clearing the personal_api_key.
    # This eliminates the Poller background thread which polls for feature flag
    # definitions every poll_interval seconds. The Poller uses shared state
    # (_flags_etag, feature_flag_definitions) without proper synchronization.
    # Feature flags will still work via remote evaluation (API calls).
    if posthoganalytics.personal_api_key:
        posthoganalytics.personal_api_key = None
        logger.info("posthog_analytics_config", action="disabled_local_evaluation")

    # Use sync mode to eliminate Consumer background threads.
    # In sync mode, capture() and other calls are made synchronously rather than
    # being queued for background processing. This is acceptable for Temporal workers
    # because we primarily use posthoganalytics for exception capture, which is
    # infrequent and not on the critical path.
    posthoganalytics.sync_mode = True
    logger.info("posthog_analytics_config", action="enabled_sync_mode")
