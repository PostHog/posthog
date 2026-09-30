# Test cases for no-drf-session-authentication semgrep rule

# ruleid: no-drf-session-authentication
from rest_framework.authentication import SessionAuthentication

# ruleid: no-drf-session-authentication
from rest_framework.authentication import SessionAuthentication as DRFSessionAuth

# ruleid: no-drf-session-authentication
from rest_framework import authentication

# ruleid: no-drf-session-authentication
x = authentication.SessionAuthentication()

# ok: no-drf-session-authentication
from posthog.auth import SessionAuthentication

# ok: no-drf-session-authentication
from rest_framework.authentication import BaseAuthentication

# ok: no-drf-session-authentication
from rest_framework import authentication