from django import forms
from django.contrib import admin, messages
from django.http import HttpRequest
from django.utils.translation import ngettext


class RedisMutationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["redis_key"].widget = forms.TextInput(attrs={"size": 50})
        self.fields["value"].widget = forms.Textarea(attrs={"rows": 10, "cols": 50})

    def save(self, commit=True):
        self.cleaned_data["status"] = "Created"
        return super().save(commit=commit)


class RedisAdmin(admin.ModelAdmin):
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

    @admin.display(description="Approvals")
    def approvals(self, obj):
        return f"{obj.approvals} / {obj.approval_threshold}: {obj.approved_by}"

    def has_module_permission(self, request):
        """Omit 'RedisAdmin' from Django admin index.

        This admin is linked directly from a custom view to tie it to other Redis-related
        views.
        """
        return False

    @admin.action(description="Approve Redis mutation")
    def approve(self, request: HttpRequest, queryset):
        user = str(request.user)

        approved = 0
        for mutation in queryset.all():
            mutation.approve(approved_by=user)
            approved += 1

        self.message_user(
            request,
            ngettext(
                "%d mutation was successfully approved by %s.",
                "%d mutations were successfully approved by %s.",
                approved,
            )
            % (approved, user),  # noqa: UP031
            messages.SUCCESS,
        )

    @admin.action(description="Mark Redis mutation as discarded")
    def discard(self, request: HttpRequest, queryset):
        user = str(request.user)

        discarded = 0
        for mutation in queryset.all():
            mutation.discarded(discarded_by=str(user))
            discarded += 1

        self.message_user(
            request,
            ngettext(
                "%d mutation was successfully discarded by %s.",
                "%d mutations were successfully discarded by %s.",
                discarded,
            )
            % (discarded, str(user)),  # noqa: UP031
            messages.SUCCESS,
        )

    @admin.action(description="Apply Redis mutation")
    def apply(self, request: HttpRequest, queryset):
        user = str(request.user)

        failures = 0
        successes = 0

        for mutation in queryset.all():
            try:
                mutation.apply(str(user))
            except Exception:
                self.message_user(
                    request,
                    "mutation on %s triggered by user %s failed" % (mutation.redis_key, str(user)),  # noqa: UP031
                    messages.ERROR,
                )
                failures += 1
            else:
                successes += 1

        if not failures:
            self.message_user(
                request,
                ngettext(
                    "%d mutation was successfully applied by %s.",
                    "%d mutations out of %d were successfully applied by %s.",
                    successes,
                )
                % (successes, successes, str(user)),  # noqa: UP031
                messages.SUCCESS,
            )
            return

        self.message_user(
            request,
            "Only %d mutations out of %d were successfully applied by %s."
            % (successes, failures + successes, str(user)),  # noqa: UP031
            messages.WARNING,
        )
