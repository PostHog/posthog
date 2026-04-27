---
title: Linking Klaviyo as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Klaviyo
---

The Klaviyo connector can link campaigns, profiles, events, flows, and more to PostHog.

To link Klaviyo:

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to Klaviyo.

3. Next, you need an API key from Klaviyo. Go to your [API keys settings](https://www.klaviyo.com/settings/account/api-keys) in Klaviyo. Click **Create Private API Key**, give it a name, and select **Read-Only Key** for the access level. Copy the value of the newly created key.

4. Back in PostHog, paste the API key in the `API key` field and click **Next**.

5. On the next page, set up the schemas you want to sync and modify the method and frequency as needed. Once done, click **Import**.

Once the syncs are complete, you can start using Klaviyo data in PostHog.
