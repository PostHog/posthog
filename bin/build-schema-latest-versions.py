import os
import sys

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from posthog.schema_migrations import LATEST_VERSIONS
from posthog.utils import to_json

# Make LATEST_VERSIONS accesible frontend-side
with open("frontend/src/queries/latest-versions.json", "wb") as f:
    f.write(to_json(LATEST_VERSIONS))
