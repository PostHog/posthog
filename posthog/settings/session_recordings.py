from posthog.settings import get_from_env, DEBUG, TEST

RECORDINGS_POST_PROCESSING_CRON = get_from_env(
    "RECORDINGS_POST_PROCESSING_CRON",
    "*/5 * * * *" if DEBUG or TEST else "12 2 * * *")