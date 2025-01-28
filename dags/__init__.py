import os

import django

# setup PostHog Django Project
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

django.setup()

from . import ch_examples, deletes, usage_report