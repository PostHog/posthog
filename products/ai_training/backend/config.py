from django.conf import settings


def privacy_enabled() -> bool:
    return bool(getattr(settings, "AI_RESEARCH_REPLAY_PRIVACY_TABLE", ""))
