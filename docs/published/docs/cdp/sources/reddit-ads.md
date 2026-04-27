---
title: Linking Reddit Ads as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
beta: true
sourceId: RedditAds
---

You can sync data from Reddit Ads reports by configuring it as a source in PostHog. The supported reports that can be synced include Ad Groups, Campaigns, Ads, Ad Group Report, Campaign Report, and Ad Report, as described here:

- [Ad Groups](https://ads-api.reddit.com/docs/v3/operations/List%20Ad%20Groups)
- [Campaigns](https://ads-api.reddit.com/docs/v3/operations/List%20Campaigns)
- [Ads](https://ads-api.reddit.com/docs/v3/operations/List%20Ads)
- [Ad Groups Report](https://ads-api.reddit.com/docs/v3/operations/Get%20A%20Report): Report broken down by `AD_GROUP_ID`
- [Campaign Report](https://ads-api.reddit.com/docs/v3/operations/Get%20A%20Report): Report broken down by `CAMPAIGN_ID`
- [Ad Report](https://ads-api.reddit.com/docs/v3/operations/Get%20A%20Report): Report broken down by `AD_ID`

Additional reports will be added based on user feedback we receive via our [in-app support form](https://app.posthog.com/#panel=support%3Afeedback%3Adata_warehouse%3Alow%3Atrue).

## Requirements

- A Reddit Ads account with permission to access data from accounts you want to sync.
- Your account ID from the [business manager app](https://ads.reddit.com/business/) > Menu > Assets > Ad Accounts > get the ID

<ProductScreenshot
    imageLight = "https://res.cloudinary.com/dmukukwp6/image/upload/Screenshot_2025_09_11_at_7_01_43_PM_c31b74db4c.png"
    classes="rounded"
    alt="Reddit account ID"
/>

## Configuring PostHog

Connect PostHog to your Reddit Ads account using a Reddit account. The Reddit account must have permission to access data.

1. In PostHog, go to the **[Data pipelines](https://app.posthog.com/data-management/sources)** tab.
2. Open the **+ New** drop-down menu in the top-right and select **Source**.
3. Find Reddit Ads in the sources list and click **Link**.
4. Enter the **Account ID** of the Reddit Ads account you want to sync.
5. Select an existing Reddit Ads account, or create a new integration
6. (Optional) Add a prefix for the table name.
