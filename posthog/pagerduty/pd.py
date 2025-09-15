from django.conf import settings

from pdpyras import EventsAPISession
from structlog import get_logger

from posthog.utils import get_instance_region

logger = get_logger(__name__)
routing_key = settings.PAGERDUTY_API_KEY


def create_incident(summary, source, severity="critical"):
    try:
        session = EventsAPISession(routing_key)
        logger.info(f"Creating PagerDuty incident with summary: {summary}, source: {source}, severity: {severity}")
        env = get_instance_region()
        session.trigger(summary=f"{summary}-{env}", source=source, severity=severity)
    except Exception as e:
        logger.warn(f"Error creating PagerDuty Incident incident: {e}")
