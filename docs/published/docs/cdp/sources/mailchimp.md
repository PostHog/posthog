---
title: Linking Mailchimp as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Mailchimp
---

The Mailchimp connector can link lists, campaigns, reports, and contacts to PostHog.

To link Mailchimp:

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to Mailchimp.

3. Next, you need an API key from Mailchimp. Go to your [API keys settings](https://us1.admin.mailchimp.com/account/api/) in Mailchimp. Click **Create A Key**, give it a name, and copy the value of the newly created key. The key should be in the format `key-dc` (e.g., `abc123def456-us6`), where the suffix after the last hyphen is your Mailchimp data center.

4. Back in PostHog, paste the API key in the `API key` field and click **Next**.

5. On the next page, set up the schemas you want to sync and modify the method and frequency as needed. Once done, click **Import**.

Once the syncs are complete, you can start using Mailchimp data in PostHog.
