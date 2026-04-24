---
title: Linking Bing Ads as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
beta: true
sourceId: BingAds
---

You can sync data from Bing Ads reports by configuring it as a source in PostHog. These are the supported entity and reports:

| Report Type                                                                                                  | Description                               |
| ------------------------------------------------------------------------------------------------------------ | ----------------------------------------- |
| [Campaigns](https://learn.microsoft.com/en-us/advertising/guides/campaign-management-guides?view=bingads-13) |                                           |
| [Campaign Performance Report](https://learn.microsoft.com/en-us/advertising/guides/reports)                  | Performance metrics at the campaign level |
| [Ad Group Performance Report](https://learn.microsoft.com/en-us/advertising/guides/reports)                  | Performance metrics at the ad group level |
| [Ad Performance Report](https://learn.microsoft.com/en-us/advertising/guides/reports)                        | Performance metrics at the ad level       |

Additional reports will be added based on user feedback we receive via our [in-app support form](https://app.posthog.com/#panel=support%3Afeedback%3Adata_warehouse%3Alow%3Atrue).

## Requirements

- A Bing Ads account with permission to access data from accounts you want to sync.
- Your **Account ID** (numeric only) from the [Bing Ads interface](https://ui.ads.microsoft.com/) > **Settings** > **Account Settings** > The account ID is visible below the **Account ID** header.

<CalloutBox icon="IconWarning" title="Don't confuse Account Number with Account ID" type="caution">

Microsoft Advertising shows both an **Account Number** and an **Account ID** in the UI:

- **Account Number** - An eight-character alphanumeric value (e.g., `A1B2C3D4`). This is NOT what you need.
- **Account ID** - A numeric-only value (e.g., `123456789`). This is what PostHog requires.

Make sure you enter the numeric **Account ID**, not the alphanumeric **Account Number**.

</CalloutBox>

<ProductScreenshot
    imageLight = "https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/Screenshot_2025_11_20_at_2_31_35_PM_57e3bef9cc.png"
    classes="rounded"
    alt="Bing Ads account ID"
/>

<CalloutBox icon="IconWarning" title="Don't confuse Account Number with Account ID" type="caution">

Microsoft Advertising has two different identifiers:

- **Account Number** - An alphanumeric, 8-character value (e.g., `AB12CD34`). This is displayed prominently in the UI but is **not** what PostHog needs.
- **Account ID** - A numeric-only value (e.g., `123456789`). This is required for the API and is what you should enter in PostHog.

You can find your **Account ID** in Microsoft Advertising under **Settings** > **Account Settings**. Make sure you use the numeric **Account ID**, not the alphanumeric **Account Number**.

</CalloutBox>

## Configuring PostHog

Connect PostHog to your Bing Ads account using a Microsoft account. The Microsoft account must have administrator or standard access to your Bing Ads account to view campaign data and reports.

1. In PostHog, go to the **[Data pipelines](https://app.posthog.com/data-management/sources)** tab.
2. Open the **+ New** drop-down menu in the top-right and select **Source**.
3. Find Bing Ads in the sources list and click **Link**.
4. Enter the **Account ID** of the Bing Ads account you want to sync.
5. Select an existing Bing Ads account, or create a new integration.
6. (Optional) Add a prefix for the table name.
