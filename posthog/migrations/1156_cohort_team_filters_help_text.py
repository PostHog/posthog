from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1155_sharingconfiguration_interviewee_context"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cohort",
            name="filters",
            field=models.JSONField(
                blank=True,
                help_text='Filters for the cohort. The `negation` field shown below is specific to\n        cohort definitions (the inner sub-filters that build a cohort). Property filters used\n        *outside* cohort definitions — e.g. on `team.test_account_filters`, insight filters, or\n        feature flag conditions — must use `operator: "in"`/`"not_in"` for cohort exclusion and\n        do NOT accept `negation`.\n\n        Examples:\n\n        # Behavioral filter (performed event)\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "OR",\n                    "values": [{\n                        "key": "address page viewed",\n                        "type": "behavioral",\n                        "value": "performed_event",\n                        "negation": false,\n                        "event_type": "events",\n                        "time_value": "30",\n                        "time_interval": "day"\n                    }]\n                }]\n            }\n        }\n\n        # Person property filter\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "promoCodes",\n                        "type": "person",\n                        "value": ["1234567890"],\n                        "negation": false,\n                        "operator": "exact"\n                    }]\n                }]\n            }\n        }\n\n        # Cohort filter (inner — within a cohort definition)\n        {\n            "properties": {\n                "type": "OR",\n                "values": [{\n                    "type": "AND",\n                    "values": [{\n                        "key": "id",\n                        "type": "cohort",\n                        "value": 8814,\n                        "negation": false\n                    }]\n                }]\n            }\n        }',
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="team",
            name="test_account_filters",
            field=models.JSONField(
                default=list,
                help_text='Filters used to identify internal/test users. Each entry is a property filter.\n\n            Supported entry types and the exact shape each accepts:\n\n            # Person property — match (or exclude) by a person property\n            {"key": "email", "type": "person", "value": "@example.com", "operator": "icontains"}\n\n            # Event property — match by an event property\n            {"key": "$host", "type": "event", "value": "localhost", "operator": "icontains"}\n\n            # Cohort membership — match (or exclude) members of a cohort.\n            # Use operator "in" for inclusion and "not_in" for exclusion. Do NOT use a\n            # `negation` field here — `negation` is specific to cohort *definitions*\n            # (the inner sub-filters that build a cohort) and is rejected by the\n            # property-filter schema.\n            {"key": "id", "type": "cohort", "value": 8814, "operator": "not_in"}\n\n            Common operators: "exact", "is_not", "icontains", "not_icontains", "regex",\n            "not_regex", "gt", "lt", "gte", "lte", "is_set", "is_not_set", "in", "not_in".',
            ),
        ),
    ]
