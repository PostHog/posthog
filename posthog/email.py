from typing import Dict

import lxml
import toronado
from django.core.mail import EmailMultiAlternatives
from django.template.loader import get_template


def inline_css(value: str) -> str:
    """
    Returns an HTML document with inline CSS.
    Forked from getsentry/sentry
    """
    tree = lxml.html.document_fromstring(value)
    toronado.inline(tree)
    # CSS media query support is inconsistent when the DOCTYPE declaration is
    # missing, so we force it to HTML5 here.
    return lxml.html.tostring(tree, doctype="<!DOCTYPE html>")


class EmailMessage:
    def __init__(self, subject: str, template_name: str, template_context: Dict = {}):
        self.subject = subject
        template = get_template(f"email/{template_name}.html")
        self.html_body = inline_css(template.render(template_context))
        self.txt_body = ""
        self.headers = {}

    def send(self, to: str) -> None:

        email_message = EmailMultiAlternatives(
            subject=self.subject, body=self.txt_body, from_email="test@posthog.com", to=[to], headers=self.headers,
        )

        email_message.attach_alternative(self.html_body, "text/html")
        email_message.send()
