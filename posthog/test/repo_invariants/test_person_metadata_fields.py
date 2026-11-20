import re
import json
from pathlib import Path

from posthog.hogql.property import PERSON_METADATA_FIELDS

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_person_metadata_fields_match_taxonomy() -> None:
    # personMetadataPropertyDefinitions in propertyDefinitionsModel.ts also lists these fields, and no test checks it.
    taxonomy = json.loads((REPO_ROOT / "frontend/src/taxonomy/core-filter-definitions-by-group.json").read_text())
    taxonomy_keys = set(taxonomy.get("person_metadata", {}).keys())

    assert PERSON_METADATA_FIELDS == taxonomy_keys, (
        "PERSON_METADATA_FIELDS in posthog/hogql/property.py must match the "
        "person_metadata group in core-filter-definitions-by-group.json. "
        "Update both, plus propertyDefinitionsModel.ts and the Rust injection."
    )


def test_person_metadata_fields_match_rust() -> None:
    # Rust skips a field it does not list, so /flags/ matches nobody on that field and reports no error.
    rust_src = (REPO_ROOT / "rust/feature-flags/src/properties/property_matching.rs").read_text()
    match = re.search(r"PERSON_METADATA_FIELDS:\s*&\[&str\]\s*=\s*&\[(.*?)\]", rust_src, re.S)
    assert match is not None, "could not find PERSON_METADATA_FIELDS in property_matching.rs"
    rust_fields = set(re.findall(r'"([^"]+)"', match.group(1)))

    assert PERSON_METADATA_FIELDS == rust_fields, (
        "PERSON_METADATA_FIELDS in posthog/hogql/property.py must match the Rust slice in "
        "rust/feature-flags/src/properties/property_matching.rs. Update both, and add a match "
        "arm in flag_matching_utils::apply_person_cohort_to_state for any new field."
    )
