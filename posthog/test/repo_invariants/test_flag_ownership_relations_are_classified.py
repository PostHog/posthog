from django.db.models.fields.reverse_related import ForeignObjectRel
from django.test import SimpleTestCase

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.ownership import _OWNING_ACCESSORS, _REFERENCE_ACCESSORS


class TestFlagOwnershipRelationsAreClassified(SimpleTestCase):
    def test_every_relation_onto_feature_flag_is_classified(self) -> None:
        owning = {accessor for accessor, _kind, _manager in _OWNING_ACCESSORS}

        # Only a reverse relation has an accessor name; the union also holds concrete fields
        # and generic foreign keys.
        actual = {
            name
            for field in FeatureFlag._meta.get_fields()
            if isinstance(field, ForeignObjectRel) and (name := field.get_accessor_name())
        }

        unclassified = actual - owning - _REFERENCE_ACCESSORS
        assert not unclassified, (
            f"These relations point at FeatureFlag but are neither owning nor a declared "
            f"reference: {sorted(unclassified)}. Approval policies are keyed on which product "
            f"owns a flag, and an unclassified relation makes those flags read as standalone, "
            f"so they keep feature_flag.* coverage nobody chose. Add each to _OWNING_ACCESSORS "
            f"or _REFERENCE_ACCESSORS in products/feature_flags/backend/ownership.py."
        )

        stale = (owning | _REFERENCE_ACCESSORS) - actual
        assert not stale, f"These classified relations no longer exist on FeatureFlag: {sorted(stale)}"
