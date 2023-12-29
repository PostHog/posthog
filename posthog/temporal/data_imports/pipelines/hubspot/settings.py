"""Hubspot source settings and constants"""

from dlt.common import pendulum

STARTDATE = pendulum.datetime(year=2000, month=1, day=1)

CONTACT = "contact"
COMPANY = "company"
DEAL = "deal"
TICKET = "ticket"
QUOTE = "quote"

CRM_CONTACTS_ENDPOINT = "/crm/v3/objects/contacts?associations=deals,tickets,quotes"
CRM_COMPANIES_ENDPOINT = "/crm/v3/objects/companies?associations=contacts,deals,tickets,quotes"
CRM_DEALS_ENDPOINT = "/crm/v3/objects/deals"
CRM_TICKETS_ENDPOINT = "/crm/v3/objects/tickets"
CRM_QUOTES_ENDPOINT = "/crm/v3/objects/quotes"

CRM_OBJECT_ENDPOINTS = {
    CONTACT: CRM_CONTACTS_ENDPOINT,
    COMPANY: CRM_COMPANIES_ENDPOINT,
    DEAL: CRM_DEALS_ENDPOINT,
    TICKET: CRM_TICKETS_ENDPOINT,
    QUOTE: CRM_QUOTES_ENDPOINT,
}

WEB_ANALYTICS_EVENTS_ENDPOINT = "/events/v3/events?objectType={objectType}&objectId={objectId}&occurredAfter={occurredAfter}&occurredBefore={occurredBefore}&sort=-occurredAt"

OBJECT_TYPE_SINGULAR = {
    "companies": COMPANY,
    "contacts": CONTACT,
    "deals": DEAL,
    "tickets": TICKET,
    "quotes": QUOTE,
}

OBJECT_TYPE_PLURAL = {v: k for k, v in OBJECT_TYPE_SINGULAR.items()}


ENDPOINTS = (
    OBJECT_TYPE_PLURAL[CONTACT],
    OBJECT_TYPE_PLURAL[DEAL],
    OBJECT_TYPE_PLURAL[COMPANY],
    OBJECT_TYPE_PLURAL[TICKET],
    OBJECT_TYPE_PLURAL[QUOTE],
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
]

DEFAULT_COMPANY_PROPS = [
    "createdate",
    "domain",
    "hs_lastmodifieddate",
    "hs_object_id",
    "name",
]

DEFAULT_CONTACT_PROPS = [
    "createdate",
    "email",
    "firstname",
    "hs_object_id",
    "lastmodifieddate",
    "lastname",
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

DEFAULT_PROPS = {
    OBJECT_TYPE_PLURAL[CONTACT]: DEFAULT_CONTACT_PROPS,
    OBJECT_TYPE_PLURAL[COMPANY]: DEFAULT_COMPANY_PROPS,
    OBJECT_TYPE_PLURAL[DEAL]: DEFAULT_DEAL_PROPS,
    OBJECT_TYPE_PLURAL[TICKET]: DEFAULT_TICKET_PROPS,
    OBJECT_TYPE_PLURAL[QUOTE]: DEFAULT_QUOTE_PROPS,
}

ALL = ("ALL",)
