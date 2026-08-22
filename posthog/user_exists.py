from django.db.models.signals import post_delete
from django.dispatch import receiver

from posthog.models.user import User

# Fresh-install detection: `login_required` redirects to `/preflight` until the first user is
# created. Cache the positive result process-wide to keep `User.objects.exists()` off every
# authenticated render (and off the database when it briefly blips). The cache is invalidated when
# a user is deleted, so an emptied instance re-checks the database and the first-user setup flow
# works again — and so the positive result never leaks across a test that deletes its users.
_any_user_exists = False


def any_user_exists() -> bool:
    global _any_user_exists
    if not _any_user_exists:
        _any_user_exists = User.objects.exists()
    return _any_user_exists


@receiver(post_delete, sender=User)
def _reset_any_user_exists_cache(sender: type[User], **kwargs: object) -> None:
    global _any_user_exists
    _any_user_exists = False
