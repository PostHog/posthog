---
title: Linking BuildBetter as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: BuildBetter
---

The BuildBetter connector can link interviews, extractions, persons, and companies to PostHog.

To link BuildBetter:

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to BuildBetter.

3. You need an API key from BuildBetter. Go to your [API & MCP settings](https://app.buildbetter.app/settings/org/api-mcp) in BuildBetter and copy your API key.

4. Back in PostHog, paste the API key in the `API key` field and click **Next**.

5. On the next page, set up the schemas you want to sync and modify the method and frequency as needed. Once done, click **Import**.

Once the syncs are complete, you can start using BuildBetter data in PostHog.
