import uuid
import importlib

import pytest

from django.apps import apps

from products.data_warehouse.backend.models import ExternalDataSource

migration_module = importlib.import_module(
    "products.data_warehouse.backend.migrations.0046_fix_vitally_region_job_inputs"
)
forwards = migration_module.forwards


@pytest.fixture
def vitally_source_factory(team):
    def _create(job_inputs):
        return ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Vitally",
            job_inputs=job_inputs,
        )

    return _create


@pytest.mark.django_db
class TestFixVitallyRegionJobInputs:
    @pytest.mark.parametrize(
        "input_job_inputs, expected_job_inputs",
        [
            (
                # Exact shape reported from prod.
                {
                    "region": {
                        "selection": {"selection": "EU", "subdomain": ""},
                        "subdomain": "None",
                    }
                },
                {"region": {"selection": "EU", "subdomain": ""}},
            ),
            (
                # US variant — prefer the outer subdomain when it's a real value.
                {
                    "region": {
                        "selection": {"selection": "US", "subdomain": ""},
                        "subdomain": "acme",
                    }
                },
                {"region": {"selection": "US", "subdomain": "acme"}},
            ),
            (
                # Outer subdomain is garbage, inner has the real one.
                {
                    "region": {
                        "selection": {"selection": "US", "subdomain": "acme"},
                        "subdomain": "None",
                    }
                },
                {"region": {"selection": "US", "subdomain": "acme"}},
            ),
            (
                # Neither subdomain is usable — fall back to empty string.
                {
                    "region": {
                        "selection": {"selection": "EU", "subdomain": ""},
                        "subdomain": "",
                    }
                },
                {"region": {"selection": "EU", "subdomain": ""}},
            ),
            (
                # Other sibling keys on job_inputs are preserved.
                {
                    "secret_token": "sk_live_abc",
                    "region": {
                        "selection": {"selection": "EU", "subdomain": ""},
                        "subdomain": "None",
                    },
                },
                {
                    "secret_token": "sk_live_abc",
                    "region": {"selection": "EU", "subdomain": ""},
                },
            ),
        ],
        ids=[
            "reported_eu_shape_heals",
            "us_outer_subdomain_preserved",
            "us_falls_back_to_inner_subdomain",
            "no_usable_subdomain_defaults_to_empty",
            "sibling_keys_preserved",
        ],
    )
    def test_forward_migration_heals_corrupted_rows(
        self, input_job_inputs, expected_job_inputs, vitally_source_factory
    ):
        source = vitally_source_factory(input_job_inputs)

        forwards(apps, None)

        source.refresh_from_db()
        assert source.job_inputs == expected_job_inputs

    @pytest.mark.parametrize(
        "job_inputs",
        [
            # Canonical shape — no-op.
            {"region": {"selection": "EU", "subdomain": ""}},
            {"region": {"selection": "US", "subdomain": "acme"}},
            # No region at all.
            {"secret_token": "sk_live_abc"},
            # region is not a dict.
            {"region": "EU"},
            # region.selection is a dict but the inner selection is unrecognised — leave it alone
            # so it surfaces in an audit rather than being silently mangled.
            {"region": {"selection": {"foo": "bar"}, "subdomain": ""}},
            {"region": {"selection": {"selection": "ZZ", "subdomain": ""}, "subdomain": ""}},
            # Non-dict job_inputs.
            None,
        ],
        ids=[
            "canonical_eu",
            "canonical_us",
            "no_region_key",
            "region_is_string",
            "inner_selection_not_a_region_key",
            "inner_selection_unrecognised_literal",
            "job_inputs_is_none",
        ],
    )
    def test_forward_migration_leaves_other_shapes_untouched(self, job_inputs, vitally_source_factory):
        source = vitally_source_factory(job_inputs)

        forwards(apps, None)

        source.refresh_from_db()
        assert source.job_inputs == job_inputs

    def test_non_vitally_sources_unaffected(self, team):
        # Deliberately construct a non-Vitally source whose `region.selection` is a dict —
        # the migration must not touch anything that isn't Vitally.
        stripe_source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={"region": {"selection": {"selection": "EU", "subdomain": ""}, "subdomain": "None"}},
        )

        forwards(apps, None)

        stripe_source.refresh_from_db()
        assert stripe_source.job_inputs == {
            "region": {"selection": {"selection": "EU", "subdomain": ""}, "subdomain": "None"}
        }
