import pytest

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


@pytest.fixture
def zendesk_ticket_record() -> dict:
    return {**MOCK_ZENDESK_TICKET_RECORD}
