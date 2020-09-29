from typing import Dict, List, Optional

import lxml
import toronado
from django.conf import settings
from django.core import exceptions, mail
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
    Returns whether email services are available on this instance (i.e. settings are in place).
    """
    return bool(settings.EMAIL_HOST)


class EmailMessage:
    def __init__(
        self, subject: str, template_name: str, template_context: Optional[Dict] = None,
    ):
        if not is_email_available():
            raise exceptions.ImproperlyConfigured(
                "Email settings not configured! Set at least the EMAIL_HOST environment variable.",
            )

        self.subject = subject
        template = get_template(f"email/{template_name}.html")
        self.html_body = inline_css(template.render(template_context))
        self.txt_body = ""
        self.headers: Dict = {}
        self.to: List[str] = []

    def add_recipient(self, address: str, name: Optional[str] = None) -> None:
        self.to.append(f'"{name}" <{address}>' if name else address)

    def send(self) -> None:
        if not self.to:
            raise ValueError("No recipients provided! Use EmailMessage.add_recipient() first!")

        messages: List = []

        for dest in self.to:
            email_message = mail.EmailMultiAlternatives(
                subject=self.subject, body=self.txt_body, to=[dest], headers=self.headers,
            )

            email_message.attach_alternative(self.html_body, "text/html")
            messages.append(email_message)

        connection = None
        try:
            connection = mail.get_connection()
            connection.open()
            connection.send_messages(messages)
        except Exception as e:
            # Handle exceptions gracefully to avoid breaking the entire task for all teams
            # but make sure they're tracked on Sentry.
            capture_exception(e)
        finally:
            # ensure that connection has been closed
            try:
                connection.close()  # type: ignore
            except Exception:
                pass
