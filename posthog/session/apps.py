from django.apps import AppConfig


class PostHogSessionConfig(AppConfig):
    name = "posthog.session"
    label = "posthog_session"
    verbose_name = "Sessions"

    def ready(self) -> None:
        import posthog.session.signals  # noqa: F401, PLC0415 — registers the post_delete session cleanup
