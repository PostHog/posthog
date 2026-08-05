"""OCSF 1.5.0 representation of activity log entries, for ingestion into a SIEM.

Values of changed fields are omitted unless the caller opts in: `detail` is a free-form diff, so
any activity type can carry the content of the changed object (notebook rejections embed whole
documents, group property writes embedded property values). Which fields changed is enough to
answer who did what and when, which is what an audit trail is for.
"""

from typing import Any

from rest_framework import serializers

from posthog.models.activity_logging.activity_log import ActivityLog

OCSF_VERSION = "1.5.0"

CLASS_UID_ACCOUNT_CHANGE = 3001
CLASS_UID_AUTHENTICATION = 3002
CLASS_UID_ENTITY_MANAGEMENT = 3004

CATEGORY_UID_IAM = 3

ACTIVITY_ID_OTHER = 99
STATUS_ID_SUCCESS = 1
STATUS_ID_FAILURE = 2

# `activity` is an unconstrained CharField with no enum and ~57 distinct values in production, so
# only the ones carrying real volume are mapped. Everything else falls through to activity_id 99
# plus activity_name, which is OCSF's documented mechanism for an unmapped source activity.
_AUTHENTICATION_ACTIVITIES = {
    "logged_in": 1,
    "logged_out": 2,
    "share_login_success": 1,
    "share_login_failed": 1,
}

_ACCOUNT_CHANGE_ACTIVITIES = {
    "scim_provisioned": 1,
    "scim_updated": 3,
    "scim_replaced": 3,
    "scim_deprovisioned": 4,
}

_ENTITY_MANAGEMENT_ACTIVITIES = {
    "created": 1,
    "create_property": 1,
    "updated": 3,
    "changed": 3,
    "config_updated": 3,
    "update_property": 3,
    "upsert_properties": 3,
    "deleted": 4,
    "bulk_deleted": 4,
    "delete_property": 4,
    "enabled": 8,
    "materialization_enabled": 8,
    "disabled": 9,
    "materialization_disabled": 9,
}

# Rejected writes and failed exports are attempts, not completed changes.
_FAILURE_ACTIVITIES = {"save_rejected_conflict", "save_rejected_stale", "export_fail"}


def _classify(activity: str) -> tuple[int, int]:
    if activity in _AUTHENTICATION_ACTIVITIES:
        return CLASS_UID_AUTHENTICATION, _AUTHENTICATION_ACTIVITIES[activity]
    if activity in _ACCOUNT_CHANGE_ACTIVITIES:
        return CLASS_UID_ACCOUNT_CHANGE, _ACCOUNT_CHANGE_ACTIVITIES[activity]
    return CLASS_UID_ENTITY_MANAGEMENT, _ENTITY_MANAGEMENT_ACTIVITIES.get(activity, ACTIVITY_ID_OTHER)


def _changes(instance: ActivityLog) -> list[dict[str, Any]]:
    detail = instance.detail or {}
    return [change for change in (detail.get("changes") or []) if isinstance(change, dict)]


class ActivityLogOCSFSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityLog
        fields: list[str] = []

    def to_representation(self, instance: ActivityLog) -> dict[str, Any]:
        class_uid, activity_id = _classify(instance.activity)
        detail = instance.detail or {}
        changes = _changes(instance)
        changed_fields = [change["field"] for change in changes if change.get("field")]

        event: dict[str, Any] = {
            "metadata": {
                "version": OCSF_VERSION,
                "product": {"name": "PostHog", "vendor_name": "PostHog"},
                "uid": str(instance.id),
            },
            # OCSF `time` is timestamp_t: epoch milliseconds as an integer. The RFC-3339 string is a
            # separate datetime_t attribute, so both are emitted rather than one in the other's place.
            "time": int(instance.created_at.timestamp() * 1000),
            "time_dt": instance.created_at.isoformat(),
            "class_uid": class_uid,
            "category_uid": CATEGORY_UID_IAM,
            "type_uid": class_uid * 100 + activity_id,
            "activity_id": activity_id,
            "status_id": STATUS_ID_FAILURE if instance.activity in _FAILURE_ACTIVITIES else STATUS_ID_SUCCESS,
            "entity": {
                "type": instance.scope,
                "uid": instance.item_id,
                "name": detail.get("name"),
            },
            "unmapped": {
                "activity": instance.activity,
                "changed_fields": changed_fields,
                "team_id": instance.team_id,
                "organization_id": str(instance.organization_id) if instance.organization_id else None,
                "was_impersonated": instance.was_impersonated,
                "is_system": instance.is_system,
                "client": instance.client,
            },
        }

        if activity_id == ACTIVITY_ID_OTHER:
            event["activity_name"] = instance.activity

        if instance.user is not None:
            event["actor"] = {
                "user": {
                    "uid": str(instance.user.uuid),
                    "email_addr": instance.user.email,
                    "name": instance.user.first_name,
                }
            }

        if instance.ip_address:
            event["src_endpoint"] = {"ip": instance.ip_address}

        if self.context.get("include_values") and changes:
            event["entity"]["data"] = {
                change["field"]: change.get("before") for change in changes if change.get("field")
            }
            event["entity_result"] = {
                "type": instance.scope,
                "uid": instance.item_id,
                "data": {change["field"]: change.get("after") for change in changes if change.get("field")},
            }

        return event
