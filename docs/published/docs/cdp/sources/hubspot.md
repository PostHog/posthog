---
title: Linking Hubspot as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Hubspot
---

The HubSpot connector can link contacts, companies, deals, emails, meetings, quotes, and tickets to PostHog.

To link Hubspot:

1. Go to the [Data pipeline page](https://app.posthog.com/data-management/sources) and the sources tab in PostHog
2. Click **New source** and select Hubspot
3. Select the Hubspot account you want to link and click **Connect app**
4. *Optional:* Add a prefix to your table names
5. Select the tables you want to import (incremental/append syncs are not supported for HubSpot tables.)
6. Click **Import**

### Customize synced properties

By default, PostHog syncs a standard set of properties for each HubSpot schema. To control which properties are synced, enable the **Customize synced properties** toggle during setup.

When enabled, a text field appears for each schema (contacts, companies, deals, tickets, quotes, emails, meetings). Enter a comma-separated list of HubSpot property names to sync. Leave a field empty to use the defaults.

The default properties for each schema are:

- **contacts** - `createdate`, `email`, `firstname`, `hs_object_id`, `hs_lead_status`, `lastmodifieddate`, `lastname`, `hs_buying_role`
- **companies** - `createdate`, `domain`, `hs_lastmodifieddate`, `hs_object_id`, `hs_csm_sentiment`, `hs_lead_status`, `name`
- **deals** - `amount`, `closedate`, `createdate`, `dealname`, `dealstage`, `hs_lastmodifieddate`, `hs_object_id`, `pipeline`, `hs_mrr`
- **tickets** - `createdate`, `content`, `hs_lastmodifieddate`, `hs_object_id`, `hs_pipeline`, `hs_pipeline_stage`, `hs_ticket_category`, `hs_ticket_priority`, `subject`
- **quotes** - `hs_createdate`, `hs_expiration_date`, `hs_lastmodifieddate`, `hs_object_id`, `hs_public_url_key`, `hs_status`, `hs_title`
- **emails** - `hs_timestamp`, `hs_email_direction`, `hs_email_html`, `hs_email_status`, `hs_email_subject`, `hs_email_text`, `hs_attachment_ids`, `hs_email_headers`
- **meetings** - `hs_timestamp`, `hs_meeting_title`, `hs_meeting_body`, `hs_internal_meeting_notes`, `hs_meeting_external_URL`, `hs_meeting_location`, `hs_meeting_start_time`, `hs_meeting_end_time`, `hs_meeting_outcome`, `hs_activity_type`, `hs_attachment_ids`

<CalloutBox icon="IconWarning" title="Changing properties requires a full resync" type="caution">

Changing the synced properties after the initial import requires a full resync of your HubSpot data. Invalid properties are automatically filtered out. If all specified properties are invalid, the defaults are used instead.

</CalloutBox>

The data warehouse then starts syncing your Hubspot data. You can see details, progress, and rows synced in the [data pipeline sources tab](https://app.posthog.com/data-management/sources).
