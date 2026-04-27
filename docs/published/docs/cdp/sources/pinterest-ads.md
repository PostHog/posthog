---
title: Linking Pinterest Ads as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
beta: true
sourceId: PinterestAds
---

You can sync data from Pinterest Ads by configuring it as a source in PostHog. The supported entities and reports include campaigns, ad groups, ads, campaign analytics, ad group analytics, and ad analytics:

- [Campaigns](https://developers.pinterest.com/docs/api/v5/campaigns-list/): Campaign entities from your Pinterest Ads account
- [Ad Groups](https://developers.pinterest.com/docs/api/v5/ad_groups-list/): Ad group entities within campaigns
- [Ads](https://developers.pinterest.com/docs/api/v5/ads-list/): Individual ad entities within ad groups
- [Campaign Analytics](https://developers.pinterest.com/docs/api/v5/campaigns-analytics/): Performance metrics at the campaign level
- [Ad Group Analytics](https://developers.pinterest.com/docs/api/v5/ad_groups-analytics/): Performance metrics at the ad group level
- [Ad Analytics](https://developers.pinterest.com/docs/api/v5/ads-analytics/): Performance metrics at the ad level

Additional reports will be added based on user feedback we receive via our [in-app support form](https://app.posthog.com/#panel=support%3Afeedback%3Adata_warehouse%3Alow%3Atrue).

## Requirements

- A Pinterest Ads account with permission to access data from the accounts you want to sync.
- Your Ad Account ID from [Pinterest Business](https://business.pinterest.com/) > Ads > select your account > the ID is in the URL or account settings.

## Configuring PostHog

Connect PostHog to your Pinterest Ads account. The Pinterest account must have permission to access the ad account data.

1. In PostHog, go to the **[Data pipelines](https://app.posthog.com/data-management/sources)** tab.
2. Open the **+ New** drop-down menu in the top-right and select **Source**.
3. Find Pinterest Ads in the sources list and click **Link**.
4. Enter the **Ad Account ID** of the Pinterest Ads account you want to sync.
5. Select an existing Pinterest Ads account, or create a new integration.
6. (Optional) Add a prefix for the table name.
