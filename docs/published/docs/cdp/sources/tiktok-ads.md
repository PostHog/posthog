---
title: Linking TikTok Ads as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
beta: true
sourceId: TikTokAds
---

You can sync data from TikTok Ads reports by configuring it as a source in PostHog. The supported reports that can be synced include Ad Groups, Campaigns, Ads, Ad Group Report, Campaign Report, and Ad Report, as described here:

- [Ad Groups](https://business-api.tiktok.com/portal/docs?id=1739314558673922)
- [Campaigns](https://business-api.tiktok.com/portal/docs?id=1739315828649986)
- [Ads](https://business-api.tiktok.com/portal/docs?id=1735735588640770)
- [Ad Groups Report](https://business-api.tiktok.com/portal/docs?id=1740302848100353): Filter by `adgroup_ids`
- [Campaign Report](https://business-api.tiktok.com/portal/docs?id=1740302848100353): Filter by `campaign_ids`
- [Ad Report](https://business-api.tiktok.com/portal/docs?id=1740302848100353): Filter by `ad_ids`

Additional reports will be added based on user feedback we receive via our [in-app support form](https://app.posthog.com/#panel=support%3Afeedback%3Adata_warehouse%3Alow%3Atrue).

## Requirements

- A TikTok Ads account with permission to access data from accounts you want to sync.
- Your account ID from the [ads manager](https://ads.tiktok.com/i18n/dashboard) > in the top right it's your account > open the dropdown > check your ad account ID or check the dashboard url, e.g `https://ads.tiktok.com/i18n/dashboard?aadvid=ID_HERE`

<ProductScreenshot
    imageLight = "https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/Screenshot_2025_09_30_at_11_25_16_AM_ab70c4f7c4.png"
    classes="rounded"
    alt="Tiktok account ID"
/>

## Configuring PostHog

Connect PostHog to your TikTok Ads account. The TikTok account must have permission to access data.

1. In PostHog, go to the **[Data pipelines](https://app.posthog.com/data-management/sources)** tab.
2. Open the **+ New** drop-down menu in the top-right and select **Source**.
3. Find Tiktok Ads in the sources list and click **Link**.
4. Enter the **Account ID** of the Tiktok Ads account you want to sync.
5. Select an existing TikTok Ads account, or create a new integration.
6. (Optional) Add a prefix for the table name.
