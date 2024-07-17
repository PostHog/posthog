from .webhook.template_webhook import template as webhook
from .helloworld.template_helloworld import template as hello_world
from .slack.template_slack import template as slack
from .hubspot.template_hubspot import template as hubspot
from .customerio.template_customerio import template as customerio
from .intercom.template_intercom import template as intercom
from .sendgrid.template_sendgrid import template as sendgrid
from .clearbit.template_clearbit import template as clearbit
from .posthog.template_posthog import template as posthog
from .aws_kinesis.template_aws_kinesis import template as aws_kinesis


HOG_FUNCTION_TEMPLATES = [
    webhook,
    hello_world,
    slack,
    hubspot,
    customerio,
    intercom,
    posthog,
    sendgrid,
    aws_kinesis,
    clearbit,
]

HOG_FUNCTION_TEMPLATES_BY_ID = {template.id: template for template in HOG_FUNCTION_TEMPLATES}

__all__ = ["HOG_FUNCTION_TEMPLATES", "HOG_FUNCTION_TEMPLATES_BY_ID"]
