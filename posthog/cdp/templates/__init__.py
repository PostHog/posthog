from .webhook.template_webhook import template as webhook
from .helloworld.template_helloworld import template as hello_world
from .slack.template_slack import template as slack
from .hubspot.template_hubspot import template as hubspot
from .customerio.template_customerio import template as customerio


HOG_FUNCTION_TEMPLATES = [webhook, hello_world, slack, hubspot, customerio]
HOG_FUNCTION_TEMPLATES_BY_ID = {template.id: template for template in HOG_FUNCTION_TEMPLATES}

__all__ = ["HOG_FUNCTION_TEMPLATES", "HOG_FUNCTION_TEMPLATES_BY_ID"]
