---
title: Linking Attio as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Attio
---

The Attio connector can link companies, people, lists, users, and workspaces to PostHog.

To link Attio:

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to Attio.

3. Next, you need an access token from Attio. Go to your [developer settings](https://attio.com/help/reference/integrations-automations/generating-an-api-key) in Attio and create a new access token with read permissions for the data you want to sync.

4. Back in PostHog, paste the access token in the `Access token` field and click **Next**.

5. On the next page, set up the schemas you want to sync and modify the method and frequency as needed. Once done, click **Import**.

Once the syncs are complete, you can start using Attio data in PostHog.
