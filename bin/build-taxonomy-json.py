import json
import os
import sys

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

filename = "frontend/src/taxonomy/core-filter-definitions-by-group.json"

with open(filename, "w") as json_file:
    json.dump(CORE_FILTER_DEFINITIONS_BY_GROUP, json_file, indent=4, sort_keys=True)
