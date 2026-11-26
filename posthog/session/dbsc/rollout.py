from enum import StrEnum

from django.conf import settings

import structlog
import posthoganalytics

from posthog.models import User

logger = structlog.get_logger(__name__)

FLAG_KEY = "device-bound-sessions"


class Mode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


def is_available() -> bool:
    return settings.DBSC_ENABLED and bool(settings.DBSC_COOKIE_SIGNING_KEYS)


def mode_for(user: User) -> Mode:
    # An unloaded flag, an unknown variant or an error gives OFF, which refuses nobody.
    if not is_available():
        return Mode.OFF
    try:
        variant = posthoganalytics.get_feature_flag(
            FLAG_KEY,
            str(user.distinct_id),
            person_properties={"email": user.email},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("dbsc_flag_unreadable", exc_info=True)
        return Mode.OFF
    try:
        return Mode(variant) if isinstance(variant, str) else Mode.OFF
    except ValueError:
        return Mode.OFF
