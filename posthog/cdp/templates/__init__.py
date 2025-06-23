from .slack.template_slack import template as slack
from .hubspot.template_hubspot import template_event as hubspot_event, template as hubspot, TemplateHubspotMigrator
from .braze.template_braze import template as braze
from .customerio.template_customerio import template as customerio, TemplateCustomerioMigrator
from .intercom.template_intercom import (
    template as intercom,
    template_send_event as intercom_send_event,
)
from .sendgrid.template_sendgrid import template as sendgrid, TemplateSendGridMigrator
from .clearbit.template_clearbit import template as clearbit
from .june.template_june import template as june
from .make.template_make import template as make
from .posthog.template_posthog import template as posthog, TemplatePostHogMigrator
from .aws_kinesis.template_aws_kinesis import template as aws_kinesis
from .twillio.template_twilio import template as twilio
from .discord.template_discord import template as discord
from .salesforce.template_salesforce import template_create as salesforce_create, template_update as salesforce_update
from .mailjet.template_mailjet import (
    template_create_contact as mailjet_create_contact,
    template_update_contact_list as mailjet_update_contact_list,
)
from .zapier.template_zapier import template as zapier
from .mailgun.template_mailgun import template_mailgun_send_email as mailgun
from .avo.template_avo import template as avo, TemplateAvoMigrator
from .loops.template_loops import template as loops, template_send_event as loops_send_event, TemplateLoopsMigrator
from .rudderstack.template_rudderstack import template as rudderstack, TemplateRudderstackMigrator
from .gleap.template_gleap import template as gleap
from .google_pubsub.template_google_pubsub import template as google_pubsub, TemplateGooglePubSubMigrator
from .engage.template_engage import template as engage, TemplateEngageMigrator
from .zendesk.template_zendesk import template as zendesk
from .knock.template_knock import template as knock
from .meta_ads.template_meta_ads import template as meta_ads
from .activecampaign.template_activecampaign import template as activecampaign
from .attio.template_attio import template as attio
from .mailchimp.template_mailchimp import template as mailchimp
from .microsoft_teams.template_microsoft_teams import template as microsoft_teams
from .linkedin_ads.template_linkedin_ads import template as linkedin_ads
from .klaviyo.template_klaviyo import template_user as klaviyo_user, template_event as klaviyo_event
from .google_cloud_storage.template_google_cloud_storage import (
    template as google_cloud_storage,
    TemplateGoogleCloudStorageMigrator,
)
from .airtable.template_airtable import template as airtable
from .brevo.template_brevo import template as brevo
from ._siteapps.template_early_access_features import template as early_access_features
from ._siteapps.template_hogdesk import template as hogdesk
from ._siteapps.template_notification_bar import template as notification_bar
from ._siteapps.template_pineapple_mode import template as pineapple_mode
from ._siteapps.template_debug_posthog import template as debug_posthog
from ._internal.template_blank import blank_site_destination, blank_site_app
from .snapchat_ads.template_pixel import template_snapchat_pixel as snapchat_pixel
from .tiktok_ads.template_tiktok_pixel import template_tiktok_pixel as tiktok_pixel

from .reddit.template_reddit_pixel import template_reddit_pixel as reddit_pixel

HOG_FUNCTION_TEMPLATES = [
    blank_site_destination,
    blank_site_app,
    slack,
    activecampaign,
    airtable,
    attio,
    avo,
    aws_kinesis,
    twilio,
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
    linkedin_ads,
    loops,
    loops_send_event,
    mailchimp,
    mailgun,
    mailjet_create_contact,
    mailjet_update_contact_list,
    make,
    meta_ads,
    microsoft_teams,
    posthog,
    reddit_pixel,
    rudderstack,
    salesforce_create,
    salesforce_update,
    sendgrid,
    snapchat_pixel,
    tiktok_pixel,
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
