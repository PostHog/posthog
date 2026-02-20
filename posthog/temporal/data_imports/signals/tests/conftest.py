import pytest

MOCK_GITHUB_ISSUE_RECORD: dict = {
    "id": 12345,
    "number": 87,
    "title": "Charts fail to render when filter contains special characters",
    "body": (
        "When I add a filter with special characters like `&` or `<` in the value, "
        "the chart component throws a rendering error and shows a blank white area. "
        "Reproducible on both Chrome and Firefox. Expected: chart renders normally with escaped values."
    ),
    "state": "open",
    "html_url": "https://github.com/acme/analytics/issues/87",
    "labels": '[{"id": 1, "name": "bug"}, {"id": 2, "name": "frontend"}]',
    "created_at": "2025-06-10T14:30:00Z",
    "updated_at": "2025-06-11T09:15:00Z",
    "comments": 3,
    "locked": False,
}


MOCK_ZENDESK_TICKET_RECORD: dict = {
    "id": 42,
    "url": "https://testcorp.zendesk.com/api/v2/tickets/42.json",
    "via": '{"channel":"api","source":{"from":{},"rel":null,"to":{}}}',
    "tags": [],
    "type": None,
    "fields": "[]",
    "status": "open",
    "subject": "Dashboard charts not loading after latest update",
    "brand_id": 1001,
    "group_id": 2001,
    "priority": "high",
    "is_public": True,
    "recipient": None,
    "created_at": "2025-01-15 10:30:00-05:00",
    "updated_at": "2025-01-16 08:15:00-05:00",
    "assignee_id": 3001,
    "description": (
        "After updating to v2.5, all dashboard charts show a loading spinner indefinitely. "
        "Clearing cache and hard refresh don't help. Console shows 403 errors on the analytics API. "
        "This affects all users in our organization."
    ),
    "external_id": None,
    "raw_subject": "Dashboard charts not loading after latest update",
    "email_cc_ids": [],
    "follower_ids": [],
    "followup_ids": [],
    "requester_id": 4001,
    "submitter_id": 4001,
    "custom_fields": "[]",
    "has_incidents": False,
    "organization_id": 5001,
    "collaborator_ids": [],
    "custom_status_id": 6001,
    "allow_attachments": True,
    "allow_channelback": False,
    "generated_timestamp": 1705500600,
    "sharing_agreement_ids": [],
    "from_messaging_channel": False,
}


MOCK_LINEAR_ISSUE_RECORD: dict = {
    "id": "abc-123-def",
    "identifier": "ENG-42",
    "title": "Dashboard widgets fail to load when timezone is set to UTC+13",
    "description": (
        "When the user's timezone is set to UTC+13 (e.g. Samoa), dashboard widgets "
        "throw a parsing error and display 'Failed to load data'. The date range picker "
        "also shows incorrect dates. Reproducible in both Chrome and Safari."
    ),
    "priority": 2,
    "priorityLabel": "High",
    "number": 42,
    "url": "https://linear.app/acme/issue/ENG-42",
    "state": '{"id": "state-1", "name": "In Progress", "type": "started", "color": "#f2c94c"}',
    "team": '{"id": "team-1", "name": "Engineering", "key": "ENG"}',
    "labels": '{"nodes": [{"id": "label-1", "name": "bug", "color": "#eb5757"}]}',
    "assignee": '{"id": "user-1", "name": "Jane Doe", "email": "jane@acme.com"}',
    "createdAt": "2025-06-10T14:30:00.000Z",
    "updatedAt": "2025-06-11T09:15:00.000Z",
    "estimate": 3,
    "completedAt": None,
    "canceledAt": None,
}


@pytest.fixture
def github_issue_record() -> dict:
    return {**MOCK_GITHUB_ISSUE_RECORD}


@pytest.fixture
def zendesk_ticket_record() -> dict:
    return {**MOCK_ZENDESK_TICKET_RECORD}


@pytest.fixture
def linear_issue_record() -> dict:
    return {**MOCK_LINEAR_ISSUE_RECORD}
