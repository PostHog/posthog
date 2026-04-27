---
title: Linking Meta Ads as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
beta: true
sourceId: MetaAds
---

You can sync data from Meta Ads reports by configuring it as a source in PostHog. The supported reports that can be synced include Adsets, Campaigns, Ads, Adset Report, Campaign Report, and Ad Report, as described here:

- [Adsets](https://developers.facebook.com/docs/marketing-api/reference/ad-account/adsets/)
- [Campaigns](https://developers.facebook.com/docs/marketing-api/reference/ad-account/campaigns/)
- [Ads](https://developers.facebook.com/docs/marketing-api/reference/ad-account/ads/)
- [Adset Insight](https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/): filtered by level = `adset`
- [Campaign Insight](https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/): filtered by level = `campaign`
- [Ad Insight](https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights/): filtered by level = `ad`

Additional reports will be added based on user feedback we receive via our [in-app support form](https://app.posthog.com/#panel=support%3Afeedback%3Adata_warehouse%3Alow%3Atrue).

## Requirements

- A Meta Ads account with permission to access data from accounts you want to sync.
- Your account ID from the [ads manager](https://adsmanager.facebook.com/) > Menu > Campaigns > Right next to the title you will see a dropdown > get the ID from the account or check the url `https://adsmanager.facebook.com/adsmanager/manage/campaigns?act=ID_HERE`

<ProductScreenshot
    imageLight = "https://res.cloudinary.com/dmukukwp6/image/upload/w_500,c_limit,q_auto,f_auto/Screenshot_2025_09_30_at_2_14_45_PM_ecce1881cf.png"
    classes="rounded"
    alt="Meta account ID"
/>

## Configuring PostHog

Connect PostHog to your Meta Ads account using a Meta account. The Meta account must have permission to access data.

1. In PostHog, go to the **[Data pipelines](https://app.posthog.com/data-management/sources)** tab.
2. Open the **+ New** drop-down menu in the top-right and select **Source**.
3. Find Meta Ads in the sources list and click **Link**.
4. Enter the **Account ID** of the Meta Ads account you want to sync.
5. Select an existing Meta Ads account, or create a new integration.
6. (Optional) Add a prefix for the table name.
