from ._internal.template_blank import blank_site_app, blank_site_destination
from ._siteapps.template_debug_posthog import template as debug_posthog
from ._siteapps.template_early_access_features import template as early_access_features
from ._siteapps.template_hogdesk import template as hogdesk
from ._siteapps.template_notification_bar import template as notification_bar
from ._siteapps.template_pineapple_mode import template as pineapple_mode
from .avo.template_avo import (
    TemplateAvoMigrator,
    template as avo,
)
from .hubspot.template_hubspot import (
    TemplateHubspotMigrator,
    template as hubspot,
    template_event as hubspot_event,
)
from .june.template_june import template as june
from .klaviyo.template_klaviyo import (
    template_event as klaviyo_event,
    template_user as klaviyo_user,
)
from .knock.template_knock import template as knock
from .kudosity.template_kudosity import template as kudosity
from .loops.template_loops import (
    TemplateLoopsMigrator,
    template as loops,
    template_send_event as loops_send_event,
)
from .mailchimp.template_mailchimp import template as mailchimp
from .mailgun.template_mailgun import template_mailgun_send_email as mailgun
from .mailjet.template_mailjet import (
    template_create_contact as mailjet_create_contact,
    template_update_contact_list as mailjet_update_contact_list,
)
from .make.template_make import template as make
from .meta_ads.template_meta_ads import template as meta_ads
from .microsoft_teams.template_microsoft_teams import template as microsoft_teams
from .onesignal.template_onesignal import template as onesignal
from .posthog.template_posthog import (
    TemplatePostHogMigrator,
    template as posthog,
)
from .reddit.template_reddit_pixel import template_reddit_pixel as reddit_pixel
from .rudderstack.template_rudderstack import (
    TemplateRudderstackMigrator,
    template as rudderstack,
)
from .salesforce.template_salesforce import (
    template_create as salesforce_create,
    template_update as salesforce_update,
)
from .sendgrid.template_sendgrid import (
    TemplateSendGridMigrator,
    template as sendgrid,
)
from .snapchat_ads.template_pixel import template_snapchat_pixel as snapchat_pixel
from .tiktok_ads.template_tiktok_pixel import template_tiktok_pixel as tiktok_pixel
from .userlist.template_userlist import template as userlist
from .zapier.template_zapier import template as zapier
from .zendesk.template_zendesk import template as zendesk

HOG_FUNCTION_TEMPLATES = [
    blank_site_destination,
    blank_site_app,
    avo,
    hubspot,
    hubspot_event,
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
    meta_ads,
    microsoft_teams,
    onesignal,
    posthog,
    reddit_pixel,
    rudderstack,
    salesforce_create,
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
    TemplateSendGridMigrator.plugin_url: TemplateSendGridMigrator,
    TemplatePostHogMigrator.plugin_url: TemplatePostHogMigrator,
    TemplateHubspotMigrator.plugin_url: TemplateHubspotMigrator,
    TemplateRudderstackMigrator.plugin_url: TemplateRudderstackMigrator,
    TemplateLoopsMigrator.plugin_url: TemplateLoopsMigrator,
    TemplateAvoMigrator.plugin_url: TemplateAvoMigrator,
}
