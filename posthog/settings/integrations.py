from posthog.settings.utils import get_from_env


SALESFORCE_CONSUMER_KEY = get_from_env("SALESFORCE_CONSUMER_KEY", "")
SALESFORCE_CONSUMER_SECRET = get_from_env("SALESFORCE_CONSUMER_SECRET", "")


"""
EXAMPLE
https://login.salesforce.com/services/oauth2/authorize
?client_id=CLIENT_ID
&redirect_uri=https://oauthdebugger.com/debug
&scope=full
&response_type=code
&response_mode=form_post
&code_challenge_method=S256
&code_challenge=2DxFjgE3BGCBZwP_Mkhvb8LDbb6OUzI_KLyAoyjaob0
&state=e1z3renyci
&nonce=pi5n8ow038
"""
