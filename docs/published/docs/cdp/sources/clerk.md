---
title: Linking Clerk as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Clerk
---

The Clerk connector can link users, organizations, organization memberships, and invitations to PostHog.

To link Clerk:

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to Clerk.

3. Next, you need a secret key from Clerk. Go to your [API keys settings](https://dashboard.clerk.com/last-active?path=api-keys) in Clerk. Copy the **Secret key** value.

4. Back in PostHog, paste the secret key in the `Secret key` field and click **Next**.

5. On the next page, set up the schemas you want to sync and modify the method and frequency as needed. Once done, click **Import**.

Once the syncs are complete, you can start using Clerk data in PostHog.
