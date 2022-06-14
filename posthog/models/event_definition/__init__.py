from posthog.settings import EE_AVAILABLE

if EE_AVAILABLE:
    from ee.models.event_definition import EnterpriseEventDefinition as EventDefinition
else:
    from posthog.models.event_definition.event_definition import EventDefinition  # type: ignore
