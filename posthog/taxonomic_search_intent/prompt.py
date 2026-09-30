"""The question, tab meanings, and confidence threshold for a filter picker search."""

from collections.abc import Mapping

from posthog.dataclasses import frozen


@frozen
class SearchIntentPrompt:
    instructions: str
    options: Mapping[str, str]
    confident_threshold: float


SEARCH_INTENT_PROMPT = SearchIntentPrompt(
    instructions="Which tab of the filter picker holds the thing this person searches for?",
    options={
        "events": "An event: something a person did, such as a pageview, a signup, a purchase or a click.",
        "actions": "A saved action: a named combination of events.",
        "event_properties": (
            "A property of one event, such as the current URL, path, browser, device, UTM tags, referrer "
            "or the country the event came from."
        ),
        "person_properties": (
            "A property of a person, such as their email address, name, company, plan or the date they signed up."
        ),
        "session_properties": (
            "A property of a whole session, such as its duration, entry URL, exit URL or channel type."
        ),
        "cohorts": "A saved cohort: a named group of people.",
        "feature_flags": "A feature flag, or the people who match a feature flag.",
        "event_feature_flags": "The value of a feature flag that was active when an event happened.",
        "pageview_urls": "One specific page URL.",
        "email_addresses": "One specific person's email address.",
        "elements": "An element on the page, such as a button, a link or a form field.",
    },
    # The frontend acts on an answer only above this confidence. Tune it from the eval suite, not by feel.
    confident_threshold=0.6,
)
