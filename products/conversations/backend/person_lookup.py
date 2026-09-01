from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.person.person import Person
from posthog.models.person.util import get_persons_by_uuids
from posthog.models.team import Team
from posthog.personhog_client.caller_tag import personhog_caller_tag

# Case-insensitive batch email lookup. Exposed so tests can EXPLAIN the exact query that runs.
# Identified persons sort first: several persons can share an email (e.g. an identified app
# user plus an email-only stub whose sole distinct_id is the address itself), and only the
# identified one carries distinct_ids that membership and analytics lookups can resolve.
# created_at prefers the oldest person, and id breaks same-millisecond ties so the
# pick is fully deterministic.
PERSON_EMAIL_LOOKUP_QUERY = """
SELECT id, properties.email
FROM persons
WHERE lower(properties.email) IN {emails}
ORDER BY is_identified DESC, created_at ASC, id ASC
"""

GROUP_KEY_BY_DISTINCT_ID_QUERY = """
SELECT distinct_id, argMaxIf({group_column}, timestamp, {group_column} != '') AS group_key
FROM events
WHERE distinct_id IN {{distinct_ids}} AND timestamp > now() - INTERVAL 90 DAY
GROUP BY distinct_id
"""


def _get_persons_by_email(
    team: Team,
    emails: list[str],
    modifiers: HogQLQueryModifiers | None = None,
) -> dict[str, Person]:
    """Batch look up persons by their properties.email value via ClickHouse.

    Returns a dict mapping lowercase email -> Person, preferring identified
    persons over unidentified ones (oldest first within each). Only checks
    ``properties.email`` (the canonical, materialized key with a skip index).
    Uses the HogQL ``persons`` virtual table (argMax dedup handled
    automatically).
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


def get_group_keys_by_email(*, team: Team, emails: list[str], group_type_index: int) -> dict[str, str | None]:
    if group_type_index not in range(5):
        return {}
    persons_by_email = _get_persons_by_email(team, emails)
    distinct_id_to_email = {
        distinct_id: email for email, person in persons_by_email.items() for distinct_id in person.distinct_ids or []
    }
    if not distinct_id_to_email:
        return {}

    group_column = f"`$group_{group_type_index}`"
    query = GROUP_KEY_BY_DISTINCT_ID_QUERY.format(group_column=group_column)
    with tags_context(product=Product.CONVERSATIONS, feature=Feature.QUERY):
        response = execute_hogql_query(
            query,
            placeholders={"distinct_ids": ast.Constant(value=sorted(distinct_id_to_email))},
            team=team,
            query_type="conversations_email_group_lookup",
        )

    group_keys_by_email: dict[str, set[str]] = {}
    for distinct_id, group_key in response.results or []:
        email = distinct_id_to_email.get(distinct_id)
        if email and group_key:
            group_keys_by_email.setdefault(email, set()).add(group_key)
    return {
        email: next(iter(group_keys)) if len(group_keys) == 1 else None
        for email, group_keys in group_keys_by_email.items()
    }
