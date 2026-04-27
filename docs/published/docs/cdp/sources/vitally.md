---
title: Linking Vitally as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Vitally
---

The Vitally connector can link accounts, conversations, notes, tasks, and more to PostHog.

To link Vitally:

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to Vitally.

3. Next, you need a secret token from Vitally. To start, click on your account logo in the top left, then **Settings**. Next, under **Operations**, select **Integrations**. Choose **Vitally REST API**, enable the integration with the toggle, and copy the secret token.

4. Back in PostHog, paste the token in the `Secret token` field, choose your Vitally region, and add a prefix for your tables if you want. Once all this is entered, click **Save**.

5. On the next page, set up the schemas you want to sync and modify the method and frequency as needed. Once done, click **Import**.

Once the syncs are complete, you can start using Vitally data in PostHog.
