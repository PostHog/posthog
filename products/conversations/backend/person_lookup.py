from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.person.person import Person
from posthog.models.person.util import get_persons_by_uuids
from posthog.models.team import Team
from posthog.personhog_client.caller_tag import personhog_caller_tag

# Case-insensitive batch email lookup. Exposed so tests can EXPLAIN the exact query that runs.
PERSON_EMAIL_LOOKUP_QUERY = """
SELECT id, properties.email
FROM persons
WHERE lower(properties.email) IN {emails}
"""


def _get_persons_by_email(
    team: Team,
    emails: list[str],
    modifiers: HogQLQueryModifiers | None = None,
) -> dict[str, Person]:
    """Batch look up persons by their properties.email value via ClickHouse.

    Returns a dict mapping lowercase email -> Person for the first match.
    Only checks ``properties.email`` (the canonical, materialized key with
    a skip index). Uses the HogQL ``persons`` virtual table (argMax dedup
    handled automatically).
    """
    if not emails:
        return {}

    emails_lower = [e.lower() for e in emails]
    with tags_context(product=Product.CONVERSATIONS, feature=Feature.QUERY):
        response = execute_hogql_query(
            PERSON_EMAIL_LOOKUP_QUERY,
            placeholders={"emails": ast.Constant(value=emails_lower)},
            team=team,
            query_type="conversations_person_email_lookup",
            modifiers=modifiers,
        )

    if not response.results:
        return {}

    email_to_uuid: dict[str, str] = {}
    for person_uuid, prop_email in response.results:
        if prop_email:
            lower = prop_email.lower()
            if lower not in email_to_uuid:
                email_to_uuid[lower] = str(person_uuid)

    with personhog_caller_tag("conversations/email-person-lookup"):
        persons = get_persons_by_uuids(team.pk, list(email_to_uuid.values()))
    uuid_to_person: dict[str, Person] = {str(p.uuid): p for p in persons}

    result: dict[str, Person] = {}
    for email_lower, person_uuid in email_to_uuid.items():
        person = uuid_to_person.get(person_uuid)
        if person is not None:
            result[email_lower] = person
    return result
