from django.db import migrations, models


def update_app_urls_and_icons(apps, schema_edirtor):
    Plugin = apps.get_model("posthog", "plugin")
    for plugin in Plugin.objects.all():
        if plugin.url in plugin_map:
            url = plugin_map[plugin.url][0]
            icon = plugin_map[plugin.url][1]
            plugin.icon = icon
            plugin.url = url
            plugin.tag = "0.0.2"
            plugin.latest_tag = "0.0.2"
            plugin.save()


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0273_mark_inactive_exports_as_finished"),
    ]

    operations = [
        migrations.AddField(
            model_name="plugin",
            name="icon",
            field=models.CharField(blank=True, max_length=800, null=True),
        ),
        migrations.RunPython(update_app_urls_and_icons),
    ]


plugin_map = {
    "https://github.com/PostHog/currency-normalization-plugin": [
        "https://www.npmjs.com/package/@posthog/currency-normalization-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/currency-normalization-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-plugin-geoip": [
        "https://www.npmjs.com/package/@posthog/geoip-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-plugin-geoip/logo.png",
    ],
    "https://github.com/PostHog/posthog-hello-world-plugin": [
        "https://www.npmjs.com/package/@posthog/hello-world-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-hello-world-plugin/logo.png",
    ],
    "https://github.com/PostHog/github-release-tracking-plugin": [
        "https://www.npmjs.com/package/@posthog/github-release-tracking-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/github-release-tracking-plugin/logo.png",
    ],
    "https://github.com/PostHog/gitlab-release-tracking-plugin": [
        "https://www.npmjs.com/package/@posthog/gitlab-release-tracking-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/gitlab-release-tracking-plugin/logo.png",
    ],
    "https://github.com/PostHog/bitbucket-release-tracker": [
        "https://www.npmjs.com/package/@posthog/bitbucket-release-tracker",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/bitbucket-release-tracker/logo.png",
    ],
    "https://github.com/PostHog/twitter-followers-plugin": [
        "https://www.npmjs.com/package/@posthog/twitter-followers-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/twitter-followers-plugin/logo.png",
    ],
    "https://github.com/PostHog/hubspot-plugin": [
        "https://www.npmjs.com/package/@posthog/hubspot-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/hubspot-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-plugin-replicator": [
        "https://www.npmjs.com/package/@posthog/replicator-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-plugin-replicator/logo.png",
    ],
    "https://www.npmjs.com/package/@posthog/schema-enforcer-plugin": [
        "https://www.npmjs.com/package/@posthog/schema-enforcer-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/schema-enforcer-plugin/logo.png",
    ],
    "https://github.com/PostHog/customerio-plugin": [
        "https://www.npmjs.com/package/@posthog/customerio-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/customerio-plugin/logo.png",
    ],
    "https://github.com/PostHog/sendgrid-plugin": [
        "https://www.npmjs.com/package/@posthog/sendgrid-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/sendgrid-plugin/logo.png",
    ],
    "https://github.com/PostHog/mailboxlayer-plugin": [
        "https://www.npmjs.com/package/@posthog/mailboxlayer-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/mailboxlayer-plugin/logo.png",
    ],
    "https://github.com/PostHog/bigquery-plugin": [
        "https://www.npmjs.com/package/@posthog/bigquery-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/bigquery-plugin/logo.png",
    ],
    "https://github.com/posthog/pubsub-plugin": [
        "https://www.npmjs.com/package/@posthog/pubsub-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/pubsub-plugin/logo.png",
    ],
    "https://github.com/PostHog/s3-export-plugin": [
        "https://www.npmjs.com/package/@posthog/s3-export-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/s3-export-plugin/logo.png",
    ],
    "https://github.com/PostHog/snowflake-export-plugin": [
        "https://www.npmjs.com/package/@posthog/snowflake-export-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/snowflake-export-plugin/logo.png",
    ],
    "https://www.npmjs.com/package/useragent-plugin": [
        "https://www.npmjs.com/package/@posthog/useragent-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/useragentplugin/logo.png",
    ],
    "https://github.com/PostHog/timestamp-parser-plugin": [
        "https://www.npmjs.com/package/@posthog/timestamp-parser-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/timestamp-parser-plugin/logo.png",
    ],
    "https://github.com/PostHog/taxonomy-plugin": [
        "https://www.npmjs.com/package/@posthog/taxonomy-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/taxonomy-plugin/logo.png",
    ],
    "https://github.com/PostHog/flatten-properties-plugin": [
        "https://www.npmjs.com/package/@posthog/property-flattener-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/flatten-properties-plugin/logo.png",
    ],
    "https://github.com/PostHog/event-sequence-timer-plugin": [
        "https://www.npmjs.com/package/@posthog/event-sequence-timer-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/event-sequence-timer-plugin/logo.png",
    ],
    "https://github.com/PostHog/first-time-event-tracker": [
        "https://www.npmjs.com/package/@posthog/first-time-event-tracker",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/first-time-event-tracker/logo.png",
    ],
    "https://github.com/PostHog/salesforce-plugin": [
        "https://www.npmjs.com/package/@posthog/salesforce-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/salesforce-plugin/logo.png",
    ],
    "https://github.com/PostHog/redshift-plugin": [
        "https://www.npmjs.com/package/@posthog/redshift-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/redshift-plugin/logo.png",
    ],
    "https://github.com/PostHog/downsampling-plugin": [
        "https://www.npmjs.com/package/@posthog/downsampling-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/downsampling-plugin/logo.png",
    ],
    "https://github.com/PostHog/postgres-plugin": [
        "https://www.npmjs.com/package/@posthog/postgres-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/postgres-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-pagerduty-plugin": [
        "https://www.npmjs.com/package/@posthog/pagerduty-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-pagerduty-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-gcs-plugin": [
        "https://www.npmjs.com/package/@posthog/gcs-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-gcs-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-automatic-cohorts-plugin": [
        "https://www.npmjs.com/package/@posthog/automatic-cohorts-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-automatic-cohorts-plugin/logo.png",
    ],
    "https://github.com/rudderlabs/rudderstack-posthog-plugin": [
        "https://www.npmjs.com/package/@posthog/rudderstack-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/rudderstack-posthog-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-orbit-love-plugin": [
        "https://www.npmjs.com/package/@posthog/orbit-love-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-orbit-love-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-redshift-import-plugin": [
        "https://www.npmjs.com/package/@posthog/redshift-import-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-redshift-import-plugin/logo.png",
    ],
    "https://github.com/PostHog/github-star-sync-plugin": [
        "https://www.npmjs.com/package/@posthog/gitub-star-sync-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/github-star-sync-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-plugin-migrator3000": [
        "https://www.npmjs.com/package/@posthog/migrator3000-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-plugin-migrator3000/logo.png",
    ],
    "https://github.com/PostHog/ingestion-alert-plugin": [
        "https://www.npmjs.com/package/@posthog/ingestion-alert-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/ingestion-alert-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-heartbeat-plugin": [
        "https://www.npmjs.com/package/@posthog/heartbeat-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-heartbeat-plugin/logo.png",
    ],
    "https://github.com/witty-works/posthog-property-filter-plugin": [
        "https://www.npmjs.com/package/@posthog/property-filter-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-property-filter-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-zendesk-plugin": [
        "https://www.npmjs.com/package/@posthog/zendesk-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-zendesk-plugin/logo.png",
    ],
    "https://github.com/netdata/posthog-netdata-event-processing": [
        "https://www.npmjs.com/package/@posthog/netdata-event-processing",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-netdata-event-processing/logo.png",
    ],
    "https://github.com/posthog/posthog-avo-plugin": [
        "https://www.npmjs.com/package/@posthog/avo-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-avo-plugin/logo.png",
    ],
    "https://github.com/PostHog/drop-events-on-property-plugin": [
        "https://www.npmjs.com/package/@posthog/drop-events-on-property-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/drop-events-on-property-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-twilio-plugin": [
        "https://www.npmjs.com/package/@posthog/twilio-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-twilio-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-intercom-plugin": [
        "https://www.npmjs.com/package/@posthog/intercom-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-intercom-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-databricks-plugin": [
        "https://www.npmjs.com/package/@posthog/databricks-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-databricks-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-kinesis-plugin": [
        "https://www.npmjs.com/package/@posthog/kinesis-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-kinesis-plugin/logo.png",
    ],
    "https://github.com/paolodamico/posthog-app-unduplicates": [
        "https://www.npmjs.com/package/@posthog/plugin-unduplicates",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-app-unduplicates/logo.png",
    ],
    "https://github.com/paolodamico/posthog-app-advanced-geoip": [
        "https://www.npmjs.com/package/@posthog/advanced-geoip-app",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-app-advanced-geoip/logo.png",
    ],
    "https://github.com/PostHog/posthog-variance-plugin": [
        "https://www.npmjs.com/package/@posthog/variance-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-variance-plugin/logo.png",
    ],
    "https://github.com/posthog/posthog-shopify-sync-plugin": [
        "https://www.npmjs.com/package/@posthog/shopify-sync-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-shopify-sync-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-engage-so-plugin": [
        "https://www.npmjs.com/package/@posthog/engage-so-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-engage-so-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-url-normalizer-plugin": [
        "https://www.npmjs.com/package/@posthog/url-normalizer-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-url-normalizer-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-patterns-app": [
        "https://www.npmjs.com/package/@posthog/patterns-app",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-patterns-app/logo.png",
    ],
    "https://github.com/PostHog/semver-flattener-plugin": [
        "https://www.npmjs.com/package/@posthog/semver-flattener-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/semver-flattener-plugin/logo.png",
    ],
    "https://github.com/PostHog/posthog-filter-out-plugin": [
        "https://www.npmjs.com/package/@posthog/filter-out-plugin",
        "https://raw.githubusercontent.com/PostHog/apps/main/src/packages/posthog-filter-out-plugin/logo.png",
    ],
}
