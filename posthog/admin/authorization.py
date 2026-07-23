from django.http import HttpRequest

# Staff access alone must not authorize irreversible org/project deletions from Django
# admin. Django's model permissions are useless as a gate here: User.is_superuser mirrors
# is_staff, so every active staff user passes has_delete_permission(). Gate destructive
# deletions behind explicit membership in this group instead — the same mechanism the
# data-deletion-request admin uses for its destructive actions.
DELETION_AUTHORIZED_GROUP = "ClickHouse Team"


def can_trigger_admin_deletion(request: HttpRequest) -> bool:
    return request.user.groups.filter(name=DELETION_AUTHORIZED_GROUP).exists()
