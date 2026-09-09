"""pgcollector embeds rust/pgcollector/ownership/table_owners.json to attribute slow queries
to teams. It is generated from the model registry and owners.yaml, so a new model, a moved
model, or an ownership change makes it stale.

Regenerate:

    bin/hogli owners:tables
"""

from pathlib import Path

from django.conf import settings

from posthog.ownership.table_owners import OUTPUT_PATH, render_json, table_owners

REGENERATE = "bin/hogli owners:tables"


def test_table_owners_json_is_fresh() -> None:
    repo_root = Path(settings.BASE_DIR)
    expected = render_json(table_owners(repo_root))
    actual = (repo_root / OUTPUT_PATH).read_text()
    assert actual == expected, f"{OUTPUT_PATH} is stale; run `{REGENERATE}` and commit the result"
