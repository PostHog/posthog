from typing import Dict, List, Optional

import lxml
import toronado
from django.conf import settings
from django.core import mail
from django.template.loader import get_template
from sentry_sdk import capture_exception


def inline_css(value: str) -> str:
    """
    Returns an HTML document with inline CSS.
    Forked from getsentry/sentry
    """
    tree = lxml.html.document_fromstring(value)
    toronado.inline(tree)
    # CSS media query support is inconsistent when the DOCTYPE declaration is
    # missing, so we force it to HTML5 here.
    return lxml.html.tostring(tree, doctype="<!DOCTYPE html>").decode("utf-8")


def is_email_available() -> bool:
    """
    Returns whether email services are available on this instance
    (i.e. settings are properly configured)
    """
    return bool(settings.EMAIL_HOST)


class EmailMessage:
    def __init__(
        self, subject: str, template_name: str, template_context: Optional[Dict] = None,
    ):
        assert is_email_available(), "email settings not configured"

        self.subject = subject
        template = get_template(f"email/{template_name}.html")
        self.html_body = inline_css(template.render(template_context))
        self.txt_body = ""
        self.headers: Dict = {}
        self.to: List[str] = []

    def add_recipient(self, address: str, name: str = "") -> None:
        if not name:
            self.to.append(address)
        else:
            self.to.append(f'"{name}" <{address}>')

    def send(self) -> None:

        assert self.to and len(self.to) > 0, "no recipients provided"

        messages: List = []

        for dest in self.to:
            email_message = mail.EmailMultiAlternatives(
                subject=self.subject, body=self.txt_body, to=[dest], headers=self.headers,
            )

            email_message.attach_alternative(self.html_body, "text/html")
            messages.append(email_message)

        try:
            connection = mail.get_connection()
            connection.open()
            connection.send_messages(messages)
            connection.close()
        except Exception as e:
            # Handle exceptions gracefully to avoid breaking the entire task for all teams
            # but make sure they're tracked on Sentry.
            capture_exception(e)
