---
title: Linking DoIt as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: DoIt
---

The DoIt connector can link infrastructure reports to PostHog.

To link DoIt:

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to DoIt.

3. Next, you need an API key from DoIt. To start, in your DoIt dashboard open up the [API key page](https://app.doit.com/profile/api), generate a key and note it down - you won't be able to view this key once you leave the page.

4. Back in PostHog, paste the API key in the `API key` field and hit **Next**.

5. On the next page, set up the reports you want to sync and modify the method and frequency as needed. Once done, click **Import**. New reports will show up in your schemas list periodically as they're created on DoIt.

Once the syncs are complete, you can start using DoIt data in PostHog.
