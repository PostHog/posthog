"""Hubspot source settings and constants"""

from dlt.common import pendulum

STARTDATE = pendulum.datetime(year=2000, month=1, day=1)

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
