import re
from unittest.mock import Mock

from posthog.management.commands.backfill_precalculated_person_properties import extract_person_property_filters
from posthog.temporal.messaging.backfill_precalculated_person_properties_coordinator_workflow import (
    PersonPropertyFilter,
)


class TestExtractPersonPropertyFilters:
    """Tests for extract_person_property_filters function."""

    def test_empty_filters_returns_empty_list(self):
        """When cohort has no filters, should return empty list."""
        cohort = Mock()
        cohort.filters = None

        result = extract_person_property_filters(cohort)

        assert result == []

    def test_filters_without_properties_returns_empty_list(self):
        """When filters object exists but has no properties key, should return empty list."""
        cohort = Mock()
        cohort.filters = {"some_other_key": "value"}

        result = extract_person_property_filters(cohort)

        assert result == []

    def test_properties_without_values_returns_empty_list(self):
        """When properties exists but has no values, should return empty list."""
        cohort = Mock()
        cohort.filters = {"properties": {}}

        result = extract_person_property_filters(cohort)

        assert result == []

    def test_extracts_single_person_property_filter(self):
        """Should extract a single person property filter with conditionHash and bytecode."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "value": "is_set",
                                "operator": "is_set",
                                "conditionHash": "abc123",
                                "bytecode": ["_H", 1, 31, 32, "$host"],
                            }
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert isinstance(result[0], PersonPropertyFilter)
        assert result[0].condition_hash == "abc123"
        assert result[0].bytecode == ["_H", 1, 31, 32, "$host"]

    def test_extracts_multiple_person_property_filters(self):
        """Should extract multiple person property filters from nested structure."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": "hash1",
                                "bytecode": ["bytecode1"],
                            },
                            {
                                "key": "$browser",
                                "type": "person",
                                "conditionHash": "hash2",
                                "bytecode": ["bytecode2"],
                            },
                        ],
                    },
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$city",
                                "type": "person",
                                "conditionHash": "hash3",
                                "bytecode": ["bytecode3"],
                            }
                        ],
                    },
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 3
        assert result[0].condition_hash == "hash1"
        assert result[1].condition_hash == "hash2"
        assert result[2].condition_hash == "hash3"

    def test_filters_out_non_person_type_filters(self):
        """Should only include filters with type='person', excluding behavioral and other types."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": "person_hash",
                                "bytecode": ["person_bytecode"],
                            },
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "conditionHash": "behavioral_hash",
                                "bytecode": ["behavioral_bytecode"],
                            },
                            {
                                "key": "id",
                                "type": "cohort",
                                "conditionHash": "cohort_hash",
                                "bytecode": ["cohort_bytecode"],
                            },
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "person_hash"
        assert result[0].bytecode == ["person_bytecode"]

    def test_skips_filters_without_condition_hash(self):
        """Should skip person property filters that don't have conditionHash."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "bytecode": ["bytecode"],
                                # Missing conditionHash
                            },
                            {
                                "key": "$browser",
                                "type": "person",
                                "conditionHash": "valid_hash",
                                "bytecode": ["valid_bytecode"],
                            },
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "valid_hash"

    def test_skips_filters_without_bytecode(self):
        """Should skip person property filters that don't have bytecode."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": "hash1",
                                # Missing bytecode
                            },
                            {
                                "key": "$browser",
                                "type": "person",
                                "conditionHash": "valid_hash",
                                "bytecode": ["valid_bytecode"],
                            },
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "valid_hash"

    def test_skips_filters_with_none_condition_hash(self):
        """Should skip filters where conditionHash is explicitly None."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": None,
                                "bytecode": ["bytecode"],
                            },
                            {
                                "key": "$browser",
                                "type": "person",
                                "conditionHash": "valid_hash",
                                "bytecode": ["valid_bytecode"],
                            },
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "valid_hash"

    def test_skips_filters_with_none_bytecode(self):
        """Should skip filters where bytecode is explicitly None."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": "hash1",
                                "bytecode": None,
                            },
                            {
                                "key": "$browser",
                                "type": "person",
                                "conditionHash": "valid_hash",
                                "bytecode": ["valid_bytecode"],
                            },
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "valid_hash"

    def test_skips_filters_with_empty_string_condition_hash(self):
        """Should skip filters where conditionHash is empty string."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": "",
                                "bytecode": ["bytecode"],
                            },
                            {
                                "key": "$browser",
                                "type": "person",
                                "conditionHash": "valid_hash",
                                "bytecode": ["valid_bytecode"],
                            },
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "valid_hash"

    def test_skips_filters_with_empty_list_bytecode(self):
        """Should skip filters where bytecode is empty list."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": "hash1",
                                "bytecode": [],
                            },
                            {
                                "key": "$browser",
                                "type": "person",
                                "conditionHash": "valid_hash",
                                "bytecode": ["valid_bytecode"],
                            },
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "valid_hash"

    def test_handles_deeply_nested_filter_structure(self):
        """Should handle deeply nested OR/AND filter structures."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "key": "$host",
                                        "type": "person",
                                        "conditionHash": "deep_hash",
                                        "bytecode": ["deep_bytecode"],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "deep_hash"

    def test_handles_mixed_valid_and_invalid_filters(self):
        """Should extract only valid filters when mixed with invalid ones."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {"key": "$host", "type": "person"},  # Missing both
                            {
                                "key": "$browser",
                                "type": "person",
                                "conditionHash": "hash1",
                            },  # Missing bytecode
                            {
                                "key": "$city",
                                "type": "person",
                                "bytecode": ["bytecode"],
                            },  # Missing conditionHash
                            {
                                "key": "$country",
                                "type": "person",
                                "conditionHash": "valid_hash",
                                "bytecode": ["valid_bytecode"],
                            },  # Valid
                            {
                                "key": "$pageview",
                                "type": "behavioral",
                                "conditionHash": "behavioral_hash",
                                "bytecode": ["behavioral_bytecode"],
                            },  # Wrong type
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "valid_hash"
        assert result[0].bytecode == ["valid_bytecode"]

    def test_handles_values_list_with_non_dict_items(self):
        """Should gracefully skip non-dict items in values list."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            None,  # Invalid
                            "string",  # Invalid
                            123,  # Invalid
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": "valid_hash",
                                "bytecode": ["valid_bytecode"],
                            },  # Valid
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "valid_hash"

    def test_preserves_complex_bytecode_structure(self):
        """Should preserve complex bytecode arrays as-is."""
        complex_bytecode = [
            "_H",
            1,
            31,
            32,
            "$host",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            12,
            {"nested": "object"},
            ["nested", "array"],
        ]
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": "complex_hash",
                                "bytecode": complex_bytecode,
                            }
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].bytecode == complex_bytecode
        # Verify it's the same reference (not copied)
        assert result[0].bytecode is complex_bytecode

    def test_handles_missing_values_key_in_group(self):
        """Should handle groups that don't have a 'values' key."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {"type": "OR"},  # Missing 'values' key
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": "valid_hash",
                                "bytecode": ["valid_bytecode"],
                            }
                        ],
                    },
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 1
        assert result[0].condition_hash == "valid_hash"

    def test_returns_distinct_filter_objects(self):
        """Should return distinct PersonPropertyFilter objects for each filter."""
        cohort = Mock()
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "$host",
                                "type": "person",
                                "conditionHash": "hash1",
                                "bytecode": ["bytecode1"],
                            },
                            {
                                "key": "$browser",
                                "type": "person",
                                "conditionHash": "hash2",
                                "bytecode": ["bytecode2"],
                            },
                        ],
                    }
                ],
            }
        }

        result = extract_person_property_filters(cohort)

        assert len(result) == 2
        assert result[0] is not result[1]
        assert isinstance(result[0], PersonPropertyFilter)
        assert isinstance(result[1], PersonPropertyFilter)
