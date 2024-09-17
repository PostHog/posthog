from .webhook.template_webhook import template as webhook
from .slack.template_slack import template as slack
from .hubspot.template_hubspot import template as hubspot, TemplateHubspotMigrator
from .braze.template_braze import template as braze
from .customerio.template_customerio import template as customerio, TemplateCustomerioMigrator
from .intercom.template_intercom import template as intercom, TemplateIntercomMigrator
from .sendgrid.template_sendgrid import template as sendgrid, TemplateSendGridMigrator
from .clearbit.template_clearbit import template as clearbit
from .posthog.template_posthog import template as posthog, TemplatePostHogMigrator
from .aws_kinesis.template_aws_kinesis import template as aws_kinesis
from .salesforce.template_salesforce import template_create as salesforce_create, template_update as salesforce_update
from .mailjet.template_mailjet import (
    template_create_contact as mailjet_create_contact,
    template_update_contact_list as mailjet_update_contact_list,
)
from .zapier.template_zapier import template as zapier
from .mailgun.template_mailgun import template_mailgun_send_email as mailgun
from .avo.template_avo import template as avo, TemplateAvoMigrator
from .loops.template_loops import template as loops, TemplateLoopsMigrator
from .rudderstack.template_rudderstack import template as rudderstack, TemplateRudderstackMigrator
from .gleap.template_gleap import template as gleap
from .google_pubsub.template_google_pubsub import template as google_pubsub, TemplateGooglePubSubMigrator
from .engage.template_engage import template as engage, TemplateEngageMigrator
from .zendesk.template_zendesk import template as zendesk
from .knock.template_knock import template as knock
from .activecampaign.template_activecampaign import template as activecampaign
from .google_cloud_storage.template_google_cloud_storage import (
    template as google_cloud_storage,
    TemplateGoogleCloudStorageMigrator,
)


HOG_FUNCTION_TEMPLATES = [
    activecampaign,
    avo,
    aws_kinesis,
    braze,
    clearbit,
    customerio,
    engage,
    gleap,
    google_cloud_storage,
    google_pubsub,
    hubspot,
    intercom,
    knock,
    loops,
    mailgun,
    mailjet_create_contact,
    mailjet_update_contact_list,
    posthog,
    rudderstack,
    salesforce_create,
    salesforce_update,
    sendgrid,
    slack,
    webhook,
    zapier,
    zendesk,
]


HOG_FUNCTION_TEMPLATES_BY_ID = {template.id: template for template in HOG_FUNCTION_TEMPLATES}

HOG_FUNCTION_MIGRATORS = {
    TemplateCustomerioMigrator.plugin_url: TemplateCustomerioMigrator,
    TemplateIntercomMigrator.plugin_url: TemplateIntercomMigrator,
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

__all__ = ["HOG_FUNCTION_TEMPLATES", "HOG_FUNCTION_TEMPLATES_BY_ID"]
