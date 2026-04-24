---
title: Linking Google Sheets as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
beta: true
sourceId: GoogleSheets
---

The Google Sheets connector can link your spreadsheets in to PostHog to be queryable.

## Syncing a worksheet

Each Google Sheets source in PostHog is a single spreadsheet where each worksheet is represented as a schema.

> Changing the name of a worksheet will require you to setup the schema in PostHog again to continue syncing it. We recommend not renaming worksheets.

The first row of the spreadsheet is treated as the column names for the table. 

### Configure Google Sheets

To connect to your Google Sheet, PostHog uses a Google Cloud service account. Thus, you must grant this service account access to your Google Sheet by following these steps:

1. Open your Google Sheet.
2. Navigate to **Share**.
3. Share the sheet with our service account by entering `google-sheets@posthog-external.iam.gserviceaccount.com` into the **Add people** field. We only require "Viewer" permissions to sync the sheet.


### Configuring PostHog

1. Go to the [sources tab](https://app.posthog.com/data-management/sources) of the data pipeline section in PostHog.

2. Click **+ New source** and then click **Link** next to Google Sheets.

3. Enter the **Google Sheets URL** of the sheet you want to sync and hit **Next**.

4. On the next page, set up the worksheets you want to sync and modify the method and frequency as needed. Once done, click **Import**. 

Once the syncs are complete, you can start using Google Sheets data in PostHog.


## Incremental and append only syncs

To enable incremental or append only syncs of your spreadsheet, we require a numerical `id` column with auto-incrementing values. This can be achieved by using the formula `=ROW()` in a column with the column header (row 1) being set to `id`. This will then sync only newly added rows to PostHog