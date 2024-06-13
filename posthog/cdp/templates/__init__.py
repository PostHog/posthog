from .webhook.template_webhook import template as webhook
from .helloworld.template_helloworld import template as hello_world


HOG_FUNCTION_TEMPLATES = [webhook, hello_world]
HOG_FUNCTION_TEMPLATES_BY_ID = {template.id: template for template in HOG_FUNCTION_TEMPLATES}

__all__ = ["HOG_FUNCTION_TEMPLATES", "HOG_FUNCTION_TEMPLATES_BY_ID"]
