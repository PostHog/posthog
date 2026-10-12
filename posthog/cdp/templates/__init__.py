from products.cdp.backend.templates._internal.template_blank import blank_site_app, blank_site_destination
from products.cdp.backend.templates.activecampaign.template_activecampaign import template as activecampaign
from products.cdp.backend.templates.airtable.template_airtable import template as airtable
from products.cdp.backend.templates.attio.template_attio import template as attio
from products.cdp.backend.templates.avo.template_avo import (
    TemplateAvoMigrator,
    template as avo,
)
from products.cdp.backend.templates.aws_kinesis.template_aws_kinesis import template as aws_kinesis
from products.cdp.backend.templates.braze.template_braze import template as braze
from products.cdp.backend.templates.brevo.template_brevo import template as brevo
from products.cdp.backend.templates.clearbit.template_clearbit import template as clearbit
from products.cdp.backend.templates.customerio.template_customerio import (
    TemplateCustomerioMigrator,
    template as customerio,
)
from products.cdp.backend.templates.discord.template_discord import template as discord
from products.cdp.backend.templates.engage.template_engage import (
    TemplateEngageMigrator,
    template as engage,
)
from products.cdp.backend.templates.gleap.template_gleap import template as gleap
from products.cdp.backend.templates.google_cloud_storage.template_google_cloud_storage import (
    TemplateGoogleCloudStorageMigrator,
    template as google_cloud_storage,
)
from products.cdp.backend.templates.google_pubsub.template_google_pubsub import (
    TemplateGooglePubSubMigrator,
    template as google_pubsub,
)
from products.cdp.backend.templates.hubspot.template_hubspot import (
    TemplateHubspotMigrator,
    template as hubspot,
    template_event as hubspot_event,
)
from products.cdp.backend.templates.intercom.template_intercom import (
    template as intercom,
    template_send_event as intercom_send_event,
)
from products.cdp.backend.templates.june.template_june import template as june
from products.cdp.backend.templates.klaviyo.template_klaviyo import (
    template_event as klaviyo_event,
    template_user as klaviyo_user,
)
from products.cdp.backend.templates.kudosity.template_kudosity import template as kudosity
from products.cdp.backend.templates.loops.template_loops import (
    TemplateLoopsMigrator,
    template as loops,
    template_send_event as loops_send_event,
)
from products.cdp.backend.templates.mailchimp.template_mailchimp import template as mailchimp
from products.cdp.backend.templates.mailgun.template_mailgun import template_mailgun_send_email as mailgun
from products.cdp.backend.templates.mailjet.template_mailjet import (
    template_create_contact as mailjet_create_contact,
    template_update_contact_list as mailjet_update_contact_list,
)
from products.cdp.backend.templates.make.template_make import template as make
from products.cdp.backend.templates.microsoft_teams.template_microsoft_teams import template as microsoft_teams
from products.cdp.backend.templates.onesignal.template_onesignal import template as onesignal
from products.cdp.backend.templates.posthog.template_posthog import (
    TemplatePostHogMigrator,
    template as posthog,
)
from products.cdp.backend.templates.reddit.template_reddit_pixel import template_reddit_pixel as reddit_pixel
from products.cdp.backend.templates.rudderstack.template_rudderstack import (
    TemplateRudderstackMigrator,
    template as rudderstack,
)
from products.cdp.backend.templates.salesforce.template_salesforce import (
    template_create as salesforce_create,
    template_lookup as salesforce_lookup,
    template_update as salesforce_update,
)
from products.cdp.backend.templates.sendgrid.template_sendgrid import (
    TemplateSendGridMigrator,
    template as sendgrid,
)
from products.cdp.backend.templates.snapchat_ads.template_pixel import template_snapchat_pixel as snapchat_pixel
from products.cdp.backend.templates.tiktok_ads.template_tiktok_pixel import template_tiktok_pixel as tiktok_pixel
from products.cdp.backend.templates.userlist.template_userlist import template as userlist
from products.cdp.backend.templates.zendesk.template_zendesk import template as zendesk

from ._siteapps.template_debug_posthog import template as debug_posthog
from ._siteapps.template_early_access_features import template as early_access_features
from ._siteapps.template_hogdesk import template as hogdesk
from ._siteapps.template_notification_bar import template as notification_bar
from ._siteapps.template_pineapple_mode import template as pineapple_mode
from .knock.template_knock import template as knock
from .zapier.template_zapier import template as zapier

HOG_FUNCTION_TEMPLATES = [
    blank_site_destination,
    blank_site_app,
    activecampaign,
    airtable,
    attio,
    avo,
    aws_kinesis,
    braze,
    brevo,
    clearbit,
    customerio,
    discord,
    engage,
    gleap,
    google_cloud_storage,
    google_pubsub,
    hubspot,
    hubspot_event,
    intercom,
    intercom_send_event,
    june,
    klaviyo_event,
    klaviyo_user,
    knock,
    kudosity,
    loops,
    loops_send_event,
    mailchimp,
    mailgun,
    mailjet_create_contact,
    mailjet_update_contact_list,
    make,
    microsoft_teams,
    onesignal,
    posthog,
    reddit_pixel,
    rudderstack,
    salesforce_create,
    salesforce_lookup,
    salesforce_update,
    sendgrid,
    snapchat_pixel,
    tiktok_pixel,
    userlist,
    zapier,
    zendesk,
    early_access_features,
    hogdesk,
    notification_bar,
    pineapple_mode,
    debug_posthog,
]


HOG_FUNCTION_MIGRATORS = {
    TemplateCustomerioMigrator.plugin_url: TemplateCustomerioMigrator,
    TemplateSendGridMigrator.plugin_url: TemplateSendGridMigrator,
    TemplateGooglePubSubMigrator.plugin_url: TemplateGooglePubSubMigrator,
    TemplateGoogleCloudStorageMigrator.plugin_url: TemplateGoogleCloudStorageMigrator,
    TemplateEngageMigrator.plugin_url: TemplateEngageMigrator,
    TemplatePostHogMigrator.plugin_url: TemplatePostHogMigrator,
    TemplateHubspotMigrator.plugin_url: TemplateHubspotMigrator,
    TemplateRudderstackMigrator.plugin_url: TemplateRudderstackMigrator,
    TemplateLoopsMigrator.plugin_url: TemplateLoopsMigrator,
    TemplateAvoMigrator.plugin_url: TemplateAvoMigrator,
}
