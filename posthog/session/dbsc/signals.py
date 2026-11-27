from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.http import HttpRequest

from loginas.utils import is_impersonated_session

from posthog.models import User
from posthog.session.dbsc import binding as bindings
from posthog.session.dbsc.rollout import Mode, mode_for


@receiver(user_logged_in)
def offer_device_binding(sender: object, user: User, request: HttpRequest, **kwargs: object) -> None:
    """Mark the session a login created as one to bind. Sessions from before a login stay unbound."""
    session = getattr(request, "session", None)
    if session is None or is_impersonated_session(request) or mode_for(user) == Mode.OFF:
        return
    if not bindings.is_bound_or_carried(session):
        bindings.new_offer(request)
