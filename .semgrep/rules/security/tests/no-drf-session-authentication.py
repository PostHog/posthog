# Test cases for no-drf-session-authentication semgrep rule

# ruleid: no-drf-session-authentication
from rest_framework.authentication import SessionAuthentication

# ruleid: no-drf-session-authentication
from rest_framework.authentication import SessionAuthentication as DRFSessionAuth

# ok: no-drf-session-authentication
from posthog.auth import SessionAuthentication

# ok: no-drf-session-authentication
from rest_framework.authentication import BaseAuthentication

# ok: no-drf-session-authentication
from rest_framework import authentication