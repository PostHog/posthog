---
title: Linking Shopify as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: Shopify
---

The Shopify connector can sync your Shopify store data into PostHog.

To sync Shopify data:

## In Shopify

1. Go to your Shopify store's admin panel at `https://admin.shopify.com/store/your-store-id`
2. Click **Settings**.
3. Click **Apps and sales channels**.
4. Click **Develop apps**.
5. **IMPORTANT:** Click **Build apps in Dev Dashboard** (legacy apps will be deprecated January 1 2026).
6. Click **Create app**.
7. Give your app a name and click **Create**.
8. You will be redirected to a screen for releasing a new version of your app. Here, you need to:
9. Set the app URL. Use the default value `https://shopify.dev/apps/default-app-home`.
10. Choose the app scopes. We recommend that you select all read options for the simplest setup.
11. Click **Release** and fill in the optional release details.
12. Go to **Home** in the Dev Dashboard and click **Install app** to install the app in your store.
13. Go to **Settings** in the Dev Dashboard and note your `Client ID` and `Secret` for later.

For more information about creating apps in Dev Dashboard see
[the Shopify docs](https://shopify.dev/docs/apps/build/dev-dashboard/create-apps-using-dev-dashboard).

## In PostHog

1. Go to the [data pipelines page](https://app.posthog.com/data-management/sources), and select the **Sources** tab.
2. Click the **+ New source** button and select Shopify by clicking the **+ Create** button.
3. Fill in your Shopify `Store ID` as well as the `Client ID` and `Secret` from above.
4. _Optional:_ Add a prefix to your table names.
5. Click **Next**.
6. Select the Shopify objects you want to sync, and make any sync configuration changes you need.
7. Click **Import**.

After these setup steps, your Shopify data will be automatically synced to the PostHog data warehouse.
You can see details and progress in the data pipelines [sources tab](https://app.posthog.com/data-management/sources).
