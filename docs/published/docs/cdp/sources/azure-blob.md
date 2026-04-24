---
title: Linking Azure as a source
sidebar: Docs
showTitle: true
availability:
  free: full
  selfServe: full
  enterprise: full
sourceId: AzureBlob
---

The data warehouse can link to data in your Azure storage accounts.

1. Create an Azure storage account
2. Create a blob container
3. Upload data and link to PostHog

## Step 1: Create an Azure storage account

Firstly, log into Azure and go to Storage Accounts, then create a storage account by following [this Azure guide](https://learn.microsoft.com/en-us/azure/storage/common/storage-account-create?tabs=azure-portal#create-a-storage-account).

## Step 2: Create a blob container

Once the storage account has been created, follow [this guide to create a blob container](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-quickstart-blobs-portal#create-a-container).

![container creation](https://res.cloudinary.com/dmukukwp6/image/upload/Screenshot_2024_07_18_at_11_08_05_cf44b9340b.png)

## Step 3: Upload data and link to PostHog

[Upload your data to the newly created container](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-quickstart-blobs-portal#upload-a-block-blob), Parquet files are the recommended format, but the connector also works with JSON and CSVs too.

Find the newly created file via the storage browser menu item. Once found, open the details and copy URL property. We need it to link the file in PostHog.

![copy blob file](https://res.cloudinary.com/dmukukwp6/image/upload/Screenshot_2024_07_15_at_17_59_09_2f888aaa2f.png)

1. Go to the [Data pipeline page](https://app.posthog.com/data-management/sources) and the sources tab in PostHog
2. Click **New source** and select Azure from the self managed section
3. Enter a name for your dataset and paste the copied URL into the "Files URL pattern" box
4. Select the correct format for your data
5. Enter the storage account name (this is name of the storage account you created in step 1)
6. Find and paste your storage account key - you can use [this Azure doc](https://learn.microsoft.com/en-us/azure/storage/common/storage-account-keys-manage?tabs=azure-portal#view-account-access-keys) to view your access keys

![linking your data in posthog](https://res.cloudinary.com/dmukukwp6/image/upload/Screenshot_2024_07_15_at_18_10_06_f93fadf82b.png)

That's it! You should be able to query the data from the PostHog SQL editor.
