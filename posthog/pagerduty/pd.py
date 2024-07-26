from pdpyras import EventsAPISession
from structlog import get_logger

from django.conf import settings


logger = get_logger(__name__)
routing_key = settings.PAGERDUTY_API_KEY
session = EventsAPISession(routing_key)


# function to create incident on pagerduty
def create_incident(summary, source, severity="critical"):
    logger.info(f"Creating PagerDuty incident with summary: {summary}, source: {source}, severity: {severity}")
    env = settings.ENVIRONMENT
    session.trigger(summary=f"{summary}-{env}", source=source, severity=severity)
