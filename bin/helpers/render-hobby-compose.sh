#!/usr/bin/env bash
set -euo pipefail

# Preserve Compose escapes and container shell variables during upgrade rendering.
envsubst '$DOMAIN $POSTHOG_SECRET $ENCRYPTION_SALT_KEYS $REGISTRY_URL $POSTHOG_APP_TAG $TLS_BLOCK'
