from .webhook.template_webhook import template as webhook
from .slack.template_slack import template as slack
from .hubspot.template_hubspot import template as hubspot
from .customerio.template_customerio import template as customerio
from .intercom.template_intercom import template as intercom
from .sendgrid.template_sendgrid import template as sendgrid
from .clearbit.template_clearbit import template as clearbit
from .posthog.template_posthog import template as posthog
from .aws_kinesis.template_aws_kinesis import template as aws_kinesis
from .salesforce.template_salesforce import template_create as salesforce_create, template_update as salesforce_update


HOG_FUNCTION_TEMPLATES = [
    slack,
    webhook,
    hubspot,
    customerio,
    intercom,
    posthog,
    sendgrid,
    aws_kinesis,
    clearbit,
    salesforce_create,
    salesforce_update,
]

HOG_FUNCTION_TEMPLATES_BY_ID = {template.id: template for template in HOG_FUNCTION_TEMPLATES}

__all__ = ["HOG_FUNCTION_TEMPLATES", "HOG_FUNCTION_TEMPLATES_BY_ID"]
