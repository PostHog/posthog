from posthog.settings.base_variables import TEST
from posthog.settings.utils import get_from_env

DEMO_MATRIX_N_CLUSTERS = get_from_env("DEMO_MATRIX_N_CLUSTERS", 3000 if not TEST else 1, type_cast=int)

E2E_SAML_DOMAIN = get_from_env("E2E_SAML_DOMAIN", "")
E2E_SAML_ENTITY_ID = get_from_env("E2E_SAML_ENTITY_ID", "")
E2E_SAML_ACS_URL = get_from_env("E2E_SAML_ACS_URL", "")
E2E_SAML_X509_CERT = get_from_env("E2E_SAML_X509_CERT", "")
