from django import forms
from django.contrib import admin, messages
from django.http import HttpRequest
from django.utils.translation import ngettext

from posthog.models.redis import MutationFailedToSaveError, MutationInactiveError


class RedisMutationForm(forms.ModelForm):
    """Custom form for 'RedisMutationAdmin' to add custom styling and defaults."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["redis_key"].widget = forms.TextInput(attrs={"size": 50})
        self.fields["value"].widget = forms.Textarea(attrs={"rows": 10, "cols": 50})

    def save(self, commit=True):
        self.cleaned_data["status"] = "Created"
        return super().save(commit=commit)


class RedisMutationAdmin(admin.ModelAdmin):
    """Manage Redis mutations via a Django admin view."""

    fields = [
        "redis_key",
        "value",
        "command",
        "approval_threshold",
        "parameters",
    ]

    list_display = [
        "redis_key",
        "value",
        "command",
        "status",
        "approvals",
        "last_approved_at",
        "applied_by",
        "applied_at",
        "discarded_by",
        "discarded_at",
    ]

    form = RedisMutationForm

    actions = ["approve", "apply", "discard"]

    @admin.display(description="Approvals")  # type: ignore
    def approvals(self, obj):
        """Full view of approvals for this particular 'RedisMutation'."""
        return f"{obj.approvals} / {obj.approval_threshold}: {obj.approved_by}"

    def has_module_permission(self, request) -> bool:
        """Omit 'RedisMutationAdmin' from Django admin index.

        This admin is linked directly from a custom view to tie it to other Redis-related
        views.
        """
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Only allow soft-deletes via discard."""
        return False

    @admin.action(description="Approve Redis mutation")  # type: ignore
    def approve(self, request: HttpRequest, queryset):
        """Action to approve the selected 'RedisMutation'.

        Redis mutations must be approved by at least `approval_threshold` unique users before being applied.
        This action uses the current user to attempt to approve the mutation.
        """
        user = str(request.user)

        approved = 0
        failures = 0
        for mutation in queryset.all():
            try:
                mutation.approve(approved_by=user)

            except MutationInactiveError:
                self.message_user(
                    request,
                    "cannot approve mutation on %(redis_key)s as it is not active" % {"redis_key": mutation.redis_key},  # noqa: UP031
                    messages.ERROR,
                )
                failures += 1

            except MutationFailedToSaveError:
                self.message_user(
                    request,
                    "mutation on %(redis_key)s could not be saved" % {"redis_key": mutation.redis_key},  # noqa: UP031
                    messages.ERROR,
                )
                failures += 1

            else:
                approved += 1

        self.message_results_of_action_to_user(
            action="approved", request=request, successes=approved, failures=failures, user=str(user)
        )

    def message_results_of_action_to_user(
        self, action: str, request: HttpRequest, successes: int, failures: int, user: str
    ):
        """Message back results of an action executed by user.

        Common method used by all actions to report back their results.
        """
        if not failures:
            self.message_user(
                request,
                ngettext(
                    "%(successes)d mutation was successfully %(action)s by %(user)s.",
                    "All %(successes)d mutations were successfully %(action)s by %(user)s.",
                    successes,
                )
                % {"successes": successes, "action": action, "user": str(user)},  # noqa: UP031
                messages.SUCCESS,
            )
            return

        if not successes:
            self.message_user(
                request,
                ngettext(
                    "%(failures)d mutation failed to be %(action)s by %(user)s.",
                    "All %(failures)d mutations failed to be %(action)s by %(user)s.",
                    successes,
                )
                % {"failures": failures, "action": action, "user": str(user)},  # noqa: UP031
                messages.ERROR,
            )
            return

        self.message_user(
            request,
            ngettext(
                "Only %(successes)d mutation out of %(total)d was successfully %(action)s by %(user)s.",
                "Only %(successes)d mutations out of %(total)d were successfully %(action)s by %(user)s.",
                successes,
            )
            % {"successes": successes, "total": successes + failures, "action": action, "user": str(user)},  # noqa: UP031
            messages.WARNING,
        )

    @admin.action(description="Discard Redis mutation")  # type: ignore
    def discard(self, request: HttpRequest, queryset):
        """Action to discard the selected 'RedisMutation'.

        Any discarded mutations cannot be used further. Trying to do so will result in an exception.
        """
        user = str(request.user)

        failures = 0
        discarded = 0
        for mutation in queryset.all():
            try:
                mutation.discard(discarded_by=str(user))

            except MutationInactiveError:
                self.message_user(
                    request,
                    "cannot discard mutation on %(redis_key)s as it is not active" % {"redis_key": mutation.redis_key},  # noqa: UP031
                    messages.ERROR,
                )
                failures += 1

            except MutationFailedToSaveError:
                self.message_user(
                    request,
                    "mutation on %(redis_key)s could not be saved" % {"redis_key": mutation.redis_key},  # noqa: UP031
                    messages.ERROR,
                )
                failures += 1

            else:
                discarded += 1

        self.message_results_of_action_to_user(
            action="discarded", request=request, successes=discarded, failures=failures, user=str(user)
        )

    @admin.action(description="Apply Redis mutation")  # type: ignore
    def apply(self, request: HttpRequest, queryset):
        user = str(request.user)

        failures = 0
        applied = 0
        for mutation in queryset.all():
            try:
                mutation.apply(str(user))
            except Exception:
                self.message_user(
                    request,
                    "mutation on %(redis_key)s triggered by %(user)s failed to apply"  # noqa: UP031
                    % {"redis_key": mutation.redis_key, "user": str(user)},
                    messages.ERROR,
                )
                failures += 1
            else:
                applied += 1

        self.message_results_of_action_to_user(
            action="applied", request=request, successes=applied, failures=failures, user=str(user)
        )
