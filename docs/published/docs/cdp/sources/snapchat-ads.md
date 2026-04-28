---
title: Linking Snapchat Ads as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
beta: true
sourceId: SnapchatAds
---

You can sync data from Snapchat Ads by configuring it as a source in PostHog. These are the supported entities and reports:

- [Campaigns](https://developers.snap.com/api/marketing-api/Ads-API/campaigns)
- [Ad Squads](https://developers.snap.com/api/marketing-api/Ads-API/ad-squads)
- [Ads](https://developers.snap.com/api/marketing-api/Ads-API/ads)
- [Campaign Stats](https://developers.snap.com/api/marketing-api/Ads-API/measurement): Performance metrics at the campaign level
- [Ad Squad Stats](https://developers.snap.com/api/marketing-api/Ads-API/measurement): Performance metrics at the ad squad level
- [Ad Stats](https://developers.snap.com/api/marketing-api/Ads-API/measurement): Performance metrics at the ad level

Additional reports will be added based on user feedback we receive via our [in-app support form](https://app.posthog.com/#panel=support%3Afeedback%3Adata_warehouse%3Alow%3Atrue).

## Requirements

- A Snapchat Ads account with permission to access data from accounts you want to sync.
- Your ad account ID from the [Snapchat Ads Manager](https://ads.snapchat.com/) > **Ad Accounts** > The ad account ID will be visible next to the account name.
- **Note:** You can also find it in the dashboard URL, e.g. `https://ads.snapchat.com/{ID_IS_HERE}/manage`.

<ProductScreenshot
    imageLight = "https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/Screenshot_2026_02_10_at_6_44_43_PM_c83b961fc0.png"
    classes="rounded"
    alt="Snapchat Ads account menu"
/>

<ProductScreenshot
    imageLight = "https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/Screenshot_2026_02_10_at_6_45_03_PM_4eced5e6a8.png"
    classes="rounded"
    alt="Snapchat Ads account ID"
/>

## Configuring PostHog

Connect PostHog to your Snapchat Ads account using a Snapchat account. The Snapchat account must have permission to access the ad account data you want to sync.

1. In PostHog, go to the **[Data pipelines](https://app.posthog.com/pipeline/sources)** tab.
2. Open the **+ New** drop-down menu in the top-right and select **Source**.
3. Find Snapchat Ads in the sources list and click **Link**.
4. Enter the **Ad Account ID** of the Snapchat Ads account you want to sync.
5. Select an existing Snapchat Ads account, or create a new integration.
6. (Optional) Add a prefix for the table name.
