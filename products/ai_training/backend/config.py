from django.conf import settings


def key_table_name() -> str:
    return str(getattr(settings, "AI_RESEARCH_REPLAY_KEY_TABLE", ""))


def v4_key_table_name() -> str:
    return str(getattr(settings, "AI_RESEARCH_V4_KEY_TABLE", ""))


def privacy_enabled() -> bool:
    return bool(key_table_name() or v4_key_table_name())
