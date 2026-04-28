---
title: Linking Chargebee as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Chargebee
---

The Chargebee connector can link customers, subscriptions, invoices, events, and more to PostHog.

To link Chargebee:

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to Chargebee.

3. Next, you need an API key from Chargebee. To start, in your Chargebee dashboard click on **Settings** in the sidebar. In the dropdown, select **Configure Chargebee**. Next, scroll down and select **API keys**. Here you should see a list of existing API keys. It is recommended to use a dedicated read-only key for this integration, so go to **+ Add API Key** and select **Read-Only Key**. Copy the value of the newly created key.

4. Back in PostHog, paste the API key in the `API key` field.

5. You will also need to provide your Chargebee's site name. You can find this in the top-left of your dashboard. It is also the same as the subdomain of your dashboard (i.e. the part before `.chargebee.com`)

6. Once you've entered these 2 pieces of information, hit **Next**.

7. On the next page, set up the schemas you want to sync and modify the method and frequency as needed. Once done, click **Import**.

Once the syncs are complete, you can start using Chargebee data in PostHog.
