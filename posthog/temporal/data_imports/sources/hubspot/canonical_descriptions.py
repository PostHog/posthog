"""Canonical, documentation-sourced descriptions for Hubspot CRM objects and properties.

Sourced from the official HubSpot CRM API reference (https://developers.hubspot.com/docs/api/crm).
Keyed by the lowercase endpoint names in `settings.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Hubspot table. Columns map to HubSpot's default CRM
properties. Endpoints/columns absent here fall back to LLM enrichment. Extend as coverage grows —
see the `implementing-warehouse-sources` skill.
"""

from posthog.temporal.data_imports.sources.common.canonical_descriptions import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "contacts": {
        "description": "A person tracked in HubSpot CRM — a lead, prospect, or customer.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/contacts",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the contact.",
            "email": "The contact's primary email address.",
            "firstname": "The contact's first name.",
            "lastname": "The contact's last name.",
            "createdate": "Date the contact was created in HubSpot.",
            "lastmodifieddate": "Date any property on the contact was last modified.",
            "hs_lead_status": "The contact's sales, prospecting, or outreach status.",
            "hs_buying_role": "The contact's role in the buying decision (e.g. decision maker, champion).",
        },
    },
    "companies": {
        "description": "An organization or business tracked in HubSpot CRM.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/companies",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the company.",
            "name": "The company's name.",
            "domain": "The company's primary website domain.",
            "createdate": "Date the company was created in HubSpot.",
            "hs_lastmodifieddate": "Date any property on the company was last modified.",
            "hs_lead_status": "The company's sales, prospecting, or outreach status.",
            "hs_csm_sentiment": "Customer success manager's recorded sentiment toward the company.",
        },
    },
    "deals": {
        "description": "A sales opportunity or transaction tracked through a pipeline in HubSpot CRM.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/deals",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the deal.",
            "dealname": "The name of the deal.",
            "amount": "The total monetary value of the deal.",
            "dealstage": "The deal's current stage within its pipeline.",
            "pipeline": "The pipeline the deal belongs to.",
            "closedate": "The date the deal is expected to close, or did close.",
            "createdate": "Date the deal was created in HubSpot.",
            "hs_lastmodifieddate": "Date any property on the deal was last modified.",
            "hs_mrr": "Monthly recurring revenue associated with the deal.",
        },
    },
    "tickets": {
        "description": "A customer support request tracked in HubSpot Service Hub.",
        "docs_url": "https://developers.hubspot.com/docs/api/crm/tickets",
        "columns": {
            "hs_object_id": "HubSpot's unique internal identifier for the ticket.",
            "subject": "Short summary of the ticket.",
            "content": "The body or description of the ticket.",
            "hs_pipeline": "The support pipeline the ticket belongs to.",
            "hs_pipeline_stage": "The ticket's current stage within its pipeline (e.g. new, waiting, closed).",
            "hs_ticket_priority": "The ticket's priority level.",
            "hs_ticket_category": "The category the ticket was filed under.",
            "createdate": "Date the ticket was created in HubSpot.",
            "hs_lastmodifieddate": "Date any property on the ticket was last modified.",
        },
    },
}
