from .webhook.template_webhook import template as webhook
from .helloworld.template_helloworld import template as hello_world


HOG_FUNCTION_TEMPLATES = [webhook, hello_world]

__all__ = ["HOG_FUNCTION_TEMPLATES"]
