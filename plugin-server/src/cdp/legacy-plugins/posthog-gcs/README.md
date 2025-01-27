# PostHog GCS Export Plugin

Export events to GCS on ingestion.

:warning: If you have low volumes of data this can cause us to ship a high number of files to blob storage and for loading into GCS. This can translate into higher than usual billing because of blob storage api calls and the time it takes to list and load small files in GCS.

## Installation

1. Visit 'Plugins' in PostHog
2. Find this plugin from the repository
3. Configure the plugin:
   1. Upload your Google Cloud key `.json` file. ([How to get the file](https://cloud.google.com/bigquery/docs/reference/libraries).)
   2. Enter your Project ID
   3. Enter your bucket name 
4. Watch events roll into GCS
   
## Questions?

### [Join the PostHog Users Slack community.](https://posthog.com/slack)
