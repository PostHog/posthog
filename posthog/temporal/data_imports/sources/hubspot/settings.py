"""Hubspot source settings and constants"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

STARTDATE = datetime(year=2000, month=1, day=1)

CONTACT = "contact"
COMPANY = "company"
DEAL = "deal"
TICKET = "ticket"
QUOTE = "quote"
EMAILS = "emails"
MEETINGS = "meetings"

CRM_CONTACTS_ENDPOINT = "/crm/v3/objects/contacts?associations=deals,tickets,quotes"
CRM_COMPANIES_ENDPOINT = "/crm/v3/objects/companies?associations=contacts,deals,tickets,quotes"
CRM_DEALS_ENDPOINT = "/crm/v3/objects/deals"
CRM_TICKETS_ENDPOINT = "/crm/v3/objects/tickets"
CRM_QUOTES_ENDPOINT = "/crm/v3/objects/quotes"
CRM_EMAILS_ENDPOINT = "/crm/v3/objects/emails"
CRM_MEETINGS_ENDPOINT = "/crm/v3/objects/meetings"


CRM_OBJECT_ENDPOINTS = {
    CONTACT: CRM_CONTACTS_ENDPOINT,
    COMPANY: CRM_COMPANIES_ENDPOINT,
    DEAL: CRM_DEALS_ENDPOINT,
    TICKET: CRM_TICKETS_ENDPOINT,
    QUOTE: CRM_QUOTES_ENDPOINT,
    EMAILS: CRM_EMAILS_ENDPOINT,
    MEETINGS: CRM_MEETINGS_ENDPOINT,
}

WEB_ANALYTICS_EVENTS_ENDPOINT = "/events/v3/events?objectType={objectType}&objectId={objectId}&occurredAfter={occurredAfter}&occurredBefore={occurredBefore}&sort=-occurredAt"

OBJECT_TYPE_SINGULAR = {
    "companies": COMPANY,
    "contacts": CONTACT,
    "deals": DEAL,
    "tickets": TICKET,
    "quotes": QUOTE,
    "emails": EMAILS,
    "meetings": MEETINGS,
}

OBJECT_TYPE_PLURAL = {v: k for k, v in OBJECT_TYPE_SINGULAR.items()}


ENDPOINTS = (
    OBJECT_TYPE_PLURAL[CONTACT],
    OBJECT_TYPE_PLURAL[DEAL],
    OBJECT_TYPE_PLURAL[COMPANY],
    OBJECT_TYPE_PLURAL[TICKET],
    OBJECT_TYPE_PLURAL[QUOTE],
    OBJECT_TYPE_PLURAL[EMAILS],
    OBJECT_TYPE_PLURAL[MEETINGS],
)

# CRM search API constants — shared between windowing and pagination logic
SEARCH_PAGE_SIZE = 200
SEARCH_RESULT_CAP = 10_000  # HubSpot returns at most 10k total results per search query
SEARCH_WINDOW_DAYS = 30
ASSOCIATIONS_BATCH_SIZE = 1000  # HubSpot v4 batch-read limit

DEFAULT_DEAL_PROPS = [
    "amount",
    "closedate",
    "createdate",
    "dealname",
    "dealstage",
    "hs_lastmodifieddate",
    "hs_object_id",
    "pipeline",
    "hs_mrr",
]

DEFAULT_COMPANY_PROPS = [
    "createdate",
    "domain",
    "hs_lastmodifieddate",
    "hs_object_id",
    "hs_csm_sentiment",
    "hs_lead_status",
    "name",
]

DEFAULT_CONTACT_PROPS = [
    "createdate",
    "email",
    "firstname",
    "hs_object_id",
    "hs_lead_status",
    "lastmodifieddate",
    "lastname",
    "hs_buying_role",
]

DEFAULT_TICKET_PROPS = [
    "createdate",
    "content",
    "hs_lastmodifieddate",
    "hs_object_id",
    "hs_pipeline",
    "hs_pipeline_stage",
    "hs_ticket_category",
    "hs_ticket_priority",
    "subject",
]

DEFAULT_QUOTE_PROPS = [
    "hs_createdate",
    "hs_expiration_date",
    "hs_lastmodifieddate",
    "hs_object_id",
    "hs_public_url_key",
    "hs_status",
    "hs_title",
]

DEFAULT_EMAIL_PROPS = [
    "hs_timestamp",
    "hs_lastmodifieddate",
    "hs_object_id",
    "hs_email_direction",
    "hs_email_html",
    "hs_email_status",
    "hs_email_subject",
    "hs_email_text",
    "hs_attachment_ids",
    "hs_email_headers",
]

DEFAULT_MEETINGS_PROPS = [
    "hs_timestamp",
    "hs_lastmodifieddate",
    "hs_object_id",
    "hs_meeting_title",
    "hs_meeting_body",
    "hs_internal_meeting_notes",
    "hs_meeting_external_URL",
    "hs_meeting_location",
    "hs_meeting_start_time",
    "hs_meeting_end_time",
    "hs_meeting_outcome",
    "hs_activity_type",
    "hs_attachment_ids",
]

DEFAULT_PROPS = {
    OBJECT_TYPE_PLURAL[CONTACT]: DEFAULT_CONTACT_PROPS,
    OBJECT_TYPE_PLURAL[COMPANY]: DEFAULT_COMPANY_PROPS,
    OBJECT_TYPE_PLURAL[DEAL]: DEFAULT_DEAL_PROPS,
    OBJECT_TYPE_PLURAL[TICKET]: DEFAULT_TICKET_PROPS,
    OBJECT_TYPE_PLURAL[QUOTE]: DEFAULT_QUOTE_PROPS,
    OBJECT_TYPE_PLURAL[EMAILS]: DEFAULT_EMAIL_PROPS,
    OBJECT_TYPE_PLURAL[MEETINGS]: DEFAULT_MEETINGS_PROPS,
}


def _incremental_field(name: str) -> IncrementalField:
    return IncrementalField(
        label=name,
        type=IncrementalFieldType.DateTime,
        field=name,
        field_type=IncrementalFieldType.DateTime,
    )


@dataclass
class HubspotEndpointConfig:
    name: str
    path: str
    associations: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: Optional[str] = None
    # Name of the HubSpot property used both as the search filter and as the incremental cursor
    # (e.g. hs_lastmodifieddate). None means the endpoint does not support incremental sync.
    cursor_filter_property_field: Optional[str] = None


HUBSPOT_ENDPOINTS: dict[str, HubspotEndpointConfig] = {
    "contacts": HubspotEndpointConfig(
        name="contacts",
        path="/crm/v3/objects/contacts",
        associations=["deals", "tickets", "quotes"],
        partition_key="createdate",
        cursor_filter_property_field="lastmodifieddate",
        incremental_fields=[_incremental_field("lastmodifieddate")],
    ),
    "companies": HubspotEndpointConfig(
        name="companies",
        path="/crm/v3/objects/companies",
        associations=["contacts", "deals", "tickets", "quotes"],
        partition_key="createdate",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    "deals": HubspotEndpointConfig(
        name="deals",
        path="/crm/v3/objects/deals",
        associations=[],
        partition_key="createdate",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    "tickets": HubspotEndpointConfig(
        name="tickets",
        path="/crm/v3/objects/tickets",
        associations=[],
        partition_key="createdate",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    "quotes": HubspotEndpointConfig(
        name="quotes",
        path="/crm/v3/objects/quotes",
        associations=[],
        partition_key="hs_createdate",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    "emails": HubspotEndpointConfig(
        name="emails",
        path="/crm/v3/objects/emails",
        associations=[],
        partition_key="hs_timestamp",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
    "meetings": HubspotEndpointConfig(
        name="meetings",
        path="/crm/v3/objects/meetings",
        associations=[],
        partition_key="hs_timestamp",
        cursor_filter_property_field="hs_lastmodifieddate",
        incremental_fields=[_incremental_field("hs_lastmodifieddate")],
    ),
}
