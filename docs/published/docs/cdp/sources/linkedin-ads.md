---
title: Linking LinkedIn Ads as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
beta: true
sourceId: LinkedinAds
---

You can sync data from LinkedIn Ads reports by configuring it as a source in PostHog. The supported reports that can be synced include Account, Campaigns, Campaign Stats, Campaign Groups and Campaign Groups Stats, as described here:
- [Accounts](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-accounts?view=li-lms-2025-08&tabs=http)
- [Campaigns](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-campaigns?view=li-lms-2025-08&viewFallbackFrom=li-lms-2023-05&tabs=http#search-for-campaigns)
- [Campaign Groups](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-campaign-groups?view=li-lms-2025-08&viewFallbackFrom=li-lms-2023-05&tabs=http#search-for-campaign-groups)
- [Campaign Stats](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting?view=li-lms-2025-08&viewFallbackFrom=li-lms-2023-05&tabs=curl#ad-analytics): Ad analytics by CAMPAIGN
- [Campaign Group Stats](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting?view=li-lms-2025-08&viewFallbackFrom=li-lms-2023-05&tabs=curl#ad-analytics): Ad analytics by CAMPAIGN_GROUP

Additional reports will be added based on user feedback we receive via our [in-app support form](https://app.posthog.com/#panel=support%3Afeedback%3Adata_warehouse%3Alow%3Atrue).

## Requirements

- A LinkedIn Ads account with permission to access data from accounts you want to sync.
- Your account ID from the campaign manager (see how in the image below, it can also be taken from the URL like `https://www.linkedin.com/campaignmanager/accounts/(ID here)/overview?businessId=personal`)

<ProductScreenshot
    imageLight = "https://res.cloudinary.com/dmukukwp6/image/upload/Screenshot_2025_09_04_at_5_12_47_PM_073654a608.png"
    classes="rounded"
    alt="LinkedIn account ID"
/>

## Configuring PostHog

Connect PostHog to your LinkedIn Ads account using a LinkedIn account. The LinkedIn account must have permission to access data.


1. In PostHog, go to the **[Data pipelines](https://app.posthog.com/data-management/sources)** tab.
2. Open the **+ New** drop-down menu in the top-right and select **Source**.
3. Find LinkedIn Ads in the sources list and click **Link**.
4. Enter the **Account ID** of the LinkedIn Ads account you want to sync.
5. Select an existing LinkedIn Ads account, or create a new integration
6. (Optional) Add a prefix for the table name.
