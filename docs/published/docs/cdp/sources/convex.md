---
title: Linking Convex as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Convex
---

The Convex connector can sync your Convex database tables to PostHog.

> **Note:** Convex streaming exports require the **Convex Professional plan**. See the [Convex pricing page](https://www.convex.dev/pricing) for details.

## Prerequisites

You need two things from your Convex project:

- **Deploy URL** – must be in the format `<something>.convex.cloud`. Find it in the Convex Dashboard under **Settings** > **URL & Deploy Key**.
- **Deploy key** – found in the same location: **Settings** > **URL & Deploy Key**.

## Linking Convex to PostHog

1. Go to the [Data pipeline page](https://app.posthog.com/data-management/sources) and the sources tab in PostHog
2. Click **New source** and select Convex
3. Enter your **Deploy URL** and **Deploy key**
4. Click **Next**, select the tables you want to sync, and then press **Import**

Once the syncs are complete, you can start using Convex data in PostHog.

### How syncing works

Convex uses its streaming export API to sync data:

- **Initial sync** – paginates through a full table snapshot using Convex's `/api/list_snapshot` endpoint.
- **Incremental sync** – fetches only changed documents using Convex's `/api/document_deltas` endpoint. All tables support incremental sync via the `_ts` field, which is a nanosecond mutation timestamp.
- **Partitioning** – data is datetime-partitioned on the `_creationTime` field.

> **Note:** If the sync cursor is older than approximately 30 days (Convex's retention window), a full resync is required.

import InboundIpAddresses from "../_snippets/inbound-ip-addresses.mdx";

<InboundIpAddresses />
