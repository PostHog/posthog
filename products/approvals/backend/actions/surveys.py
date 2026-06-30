from typing import Any, Optional

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

from products.approvals.backend.actions.base import BaseAction
from products.approvals.backend.exceptions import ApplyFailed, PreconditionFailed
from products.surveys.backend.models import Survey


def _survey_should_have_active_flags(survey: Survey) -> bool:
    """Mirror of SurveySerializer._should_survey_flags_be_active — a survey's managed flags
    are active exactly while it is running (launched, not ended, not archived)."""
    return bool(survey.start_date) and not survey.end_date and not survey.archived


class LaunchSurveyAction(BaseAction):
    """Gate launching a survey — the draft -> running transition (setting `start_date`).

    Surveys can be launched two ways, and both are gated:
    - a PATCH that sets `start_date` (goes through SurveySerializerCreateUpdateOnly.update), and
    - the dedicated `POST /surveys/:id/launch/` viewset action (no request body).
    """

    key = "survey.launch"
    version = 1
    description = "Launch a survey"
    resource_type = "survey"
    intent_fields = ["start_date"]

    @staticmethod
    def _is_serializer_context(view: Any) -> bool:
        return hasattr(view, "context") and isinstance(view.context, dict) and "request" in view.context

    @classmethod
    def detect(cls, request: Any, view: Any, *args: Any, **kwargs: Any) -> bool:
        try:
            survey = cls._get_instance(view, *args, **kwargs)
        except Exception:
            return False

        if survey is None:
            return False

        # Only the initial draft -> running transition is gated. A survey that is already
        # launched (re-launch no-op), archived, or being resumed is out of scope.
        if survey.start_date is not None or survey.archived:
            return False

        # On the PATCH/serializer path, it is only a launch if the request actually sets
        # start_date — a plain edit of a draft must pass through ungated. The dedicated
        # launch action carries no body, so reaching it is itself the launch intent.
        if cls._is_serializer_context(view) and not request.data.get("start_date"):
            return False

        return cls._get_team(view) is not None

    @classmethod
    def extract_intent(cls, request: Any, view: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        survey = cls._get_instance(view, *args, **kwargs)

        if cls._is_serializer_context(view):
            full_request_data = dict(request.data)
            requested_start = full_request_data.get("start_date")
        else:
            # Dedicated launch action: launch starts the survey now.
            requested_start = timezone.now().isoformat()
            full_request_data = {"start_date": requested_start}

        return {
            "survey_id": str(survey.id),
            "survey_name": survey.name,
            "current_state": {"start_date": survey.start_date.isoformat() if survey.start_date else None},
            "gated_changes": {"start_date": requested_start},
            "full_request_data": full_request_data,
            "preconditions": {
                "updated_at": survey.updated_at.isoformat() if survey.updated_at else None,
            },
        }

    @classmethod
    def validate_intent(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, Optional[dict[str, Any]]]:
        # The only gated change is the launch transition itself, which the action controls;
        # there is no client-supplied field to validate against a serializer. Launchability
        # (archived / already ended / staleness) is enforced at apply time against a locked row.
        if not intent_data.get("survey_id"):
            return False, {"survey": "Missing survey reference"}
        return True, None

    @classmethod
    def check_staleness(
        cls,
        intent_data: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> bool:
        instance = context.get("instance") if context else None
        if instance is None:
            return True

        stored_updated_at = intent_data.get("preconditions", {}).get("updated_at")
        if stored_updated_at is not None and instance.updated_at and instance.updated_at.isoformat() != stored_updated_at:
            return True

        return False

    @classmethod
    def prepare_context(cls, change_request: Any, base_context: dict[str, Any]) -> dict[str, Any]:
        context = base_context.copy()

        survey_id = change_request.intent.get("survey_id") or change_request.resource_id
        if survey_id:
            try:
                context["instance"] = Survey.objects.get(id=survey_id, team_id=change_request.team_id)
            except Survey.DoesNotExist:
                pass

        return context

    @classmethod
    def apply(cls, validated_intent: dict[str, Any], user: Any, context: Optional[dict[str, Any]] = None) -> Survey:
        survey_id = validated_intent["survey_id"]

        with transaction.atomic():
            # nosemgrep: idor-lookup-without-team (survey_id from validated change request intent, originally team-scoped)
            survey = Survey.objects.select_for_update().get(id=survey_id)

            stored_updated_at = validated_intent.get("preconditions", {}).get("updated_at")
            if stored_updated_at and survey.updated_at and survey.updated_at.isoformat() != stored_updated_at:
                raise PreconditionFailed(
                    f"Survey was modified since approval was requested "
                    f"(expected updated_at {stored_updated_at}, got {survey.updated_at.isoformat()})"
                )

            if survey.archived:
                raise ApplyFailed("Cannot launch an archived survey")

            now = timezone.now()
            if survey.end_date is not None and survey.end_date <= now:
                raise ApplyFailed("Cannot launch a survey whose end date has already passed")

            # Idempotency: already launched.
            if survey.start_date is not None:
                return survey

            requested_start = validated_intent.get("gated_changes", {}).get("start_date")
            start_date = parse_datetime(requested_start) if isinstance(requested_start, str) else None
            if start_date is None:
                start_date = now

            previous_start = survey.start_date
            survey.start_date = start_date
            survey.save(update_fields=["start_date"])

            # Mirror the serializer's launch-time lifecycle sync: a running survey's managed
            # flags must be active so it is actually shown. The user-owned linked_flag is left
            # untouched, exactly as the serializer leaves it.
            should_be_active = _survey_should_have_active_flags(survey)
            for managed_flag in (
                survey.targeting_flag,
                survey.internal_targeting_flag,
                survey.internal_response_sampling_flag,
            ):
                if managed_flag is not None and managed_flag.active != should_be_active:
                    managed_flag.active = should_be_active
                    managed_flag.save()

            log_activity(
                organization_id=survey.team.organization_id,
                team_id=survey.team_id,
                user=user,
                was_impersonated=False,
                item_id=survey.id,
                scope="Survey",
                activity="launched",
                detail=Detail(
                    name=survey.name,
                    changes=[
                        Change(
                            type="Survey",
                            action="changed",
                            field="start_date",
                            before=previous_start,
                            after=survey.start_date,
                        )
                    ],
                ),
            )

        return survey

    @classmethod
    def get_display_data(cls, intent_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "description": f"Launch survey '{intent_data.get('survey_name', 'unknown')}'",
            "before": intent_data.get("current_state", {}),
            "after": intent_data.get("gated_changes", {}),
        }
