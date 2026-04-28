---
title: Linking Temporal.io as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: TemporalIO
---

The Temporal.io connector can link workflows and workflow history to PostHog.

To link Temporal.io:

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to Temporal.io.

3. We only allow TLS certificate connections to your temporal namespace, so you need to ensure your namespace has a [certificate](https://docs.temporal.io/cloud/certificates) set up. Once done, copy all the same TLS certificate values into PostHog.

4. On the next page, set up the schemas you want to sync and modify the method and frequency as needed. Once done, click **Import**.

Once the syncs are complete, you can start using Temporal.io data in PostHog.
