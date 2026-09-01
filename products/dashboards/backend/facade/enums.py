"""
Shared enums for the dashboards product.

``DashboardAccessMethod`` labels how a dashboard render was reached. It lives in the facade
rather than in ``backend/access.py`` because the insight API tags its own cache metrics with
it, and a data type that crosses the product boundary belongs here.

``RestrictionLevel`` and ``PrivilegeLevel`` are the collaboration levels the ``Dashboard`` model
stores and every caller compares against. They are defined here for the same reason: the insight
API reports an insight's effective levels and gates dashboard edits on ``CAN_EDIT``. The model
keeps ``Dashboard.RestrictionLevel`` / ``Dashboard.PrivilegeLevel`` as aliases of these.
"""

from enum import StrEnum

from django.db import models


class DashboardAccessMethod(StrEnum):
    HUMAN = "human"
    SHARED = "shared"
    EMBEDDED = "embedded"
    API = "api"


class RestrictionLevel(models.IntegerChoices):
    """Collaboration restriction level (which is a dashboard setting). Sync with PrivilegeLevel."""

    EVERYONE_IN_PROJECT_CAN_EDIT = 21, "Everyone in the project can edit"
    ONLY_COLLABORATORS_CAN_EDIT = (
        37,
        "Only those invited to this dashboard can edit",
    )


class PrivilegeLevel(models.IntegerChoices):
    """Collaboration privilege level (which is a user property). Sync with RestrictionLevel."""

    CAN_VIEW = 21, "Can view dashboard"
    CAN_EDIT = 37, "Can edit dashboard"
