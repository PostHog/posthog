"""
Django settings for PostHog Enterprise Edition.
"""
import os
from typing import Dict, List

from posthog.constants import RDBMS
from posthog.settings import AUTHENTICATION_BACKENDS, PRIMARY_DB, SITE_URL, TEST

# Zapier REST hooks
HOOK_EVENTS: Dict[str, str] = {
    # "event_name": "App.Model.Action" (created/updated/deleted)
    "action_defined": "posthog.Action.created_custom",
    "action_performed": "posthog.Action.performed",
    "annotation_created": "posthog.Annotation.created_custom",
}
HOOK_FINDER = "ee.models.hook.find_and_fire_hook"
HOOK_DELIVERER = "ee.models.hook.deliver_hook_wrapper"

# Social auth
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = os.getenv("SOCIAL_AUTH_GOOGLE_OAUTH2_KEY")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.getenv("SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET")
if "SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS" in os.environ:
    SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS: List[str] = os.environ[
        "SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS"
    ].split(",")

AUTHENTICATION_BACKENDS = AUTHENTICATION_BACKENDS + [
    "social_core.backends.google.GoogleOAuth2",
]

# SAML
SAML_CONFIGURED = False

if os.getenv("SAML_ENTITY_ID") and os.getenv("SAML_ACS_URL") and os.getenv("SAML_X509_CERT"):
    SAML_CONFIGURED = True
    AUTHENTICATION_BACKENDS = AUTHENTICATION_BACKENDS + [
        "social_core.backends.saml.SAMLAuth",
    ]

    SOCIAL_AUTH_SAML_SP_ENTITY_ID = SITE_URL
    SOCIAL_AUTH_SAML_SECURITY_CONFIG = {
        "wantAttributeStatement": False,  # AttributeStatement is optional in the specification
    }

    SOCIAL_AUTH_SAML_ENABLED_IDPS = {
        "posthog_custom": {
            "entity_id": os.getenv("SAML_ENTITY_ID"),
            "url": os.getenv("SAML_ACS_URL"),
            "x509cert": os.getenv("SAML_X509_CERT"),
            "attr_user_permanent_id": os.getenv("SAML_ATTR_PERMANENT_ID", "name_id"),
            "attr_first_name": os.getenv("SAML_ATTR_FIRST_NAME", "first_name"),
            "attr_last_name": os.getenv("SAML_ATTR_LAST_NAME", "last_name"),
            "attr_email": os.getenv("SAML_ATTR_EMAIL", "email"),
        },
    }

    # Attributes below are required for the SAML integration from social_core to work properly
    SOCIAL_AUTH_SAML_SP_PUBLIC_CERT = ""
    SOCIAL_AUTH_SAML_SP_PRIVATE_KEY = ""
    SOCIAL_AUTH_SAML_ORG_INFO = {"en-US": {"name": "posthog", "displayname": "PostHog", "url": "https://posthog.com"}}
    SOCIAL_AUTH_SAML_TECHNICAL_CONTACT = {"givenName": "PostHog Support", "emailAddress": "hey@posthog.com"}
    SOCIAL_AUTH_SAML_SUPPORT_CONTACT = SOCIAL_AUTH_SAML_TECHNICAL_CONTACT

# ClickHouse and Kafka
KAFKA_ENABLED = PRIMARY_DB == RDBMS.CLICKHOUSE and not TEST
