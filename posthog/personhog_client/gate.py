from __future__ import annotations

import random

from django.conf import settings


def use_personhog() -> bool:
    if not getattr(settings, "PERSONHOG_ENABLED", False):
        return False

    if not getattr(settings, "PERSONHOG_ADDR", ""):
        return False

    rollout_pct = getattr(settings, "PERSONHOG_ROLLOUT_PERCENTAGE", 0)

    if rollout_pct >= 100:
        return True
    if rollout_pct <= 0:
        return False

    return random.randint(1, 100) <= rollout_pct
