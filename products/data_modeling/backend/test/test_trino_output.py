from uuid import UUID

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.data_modeling.backend.logic.trino_output import trino_output_folder

SAVED_QUERY_ID = UUID("0192a000-0000-7000-8000-000000000001")


class TestTrinoOutputFolder(SimpleTestCase):
    def _folder(self, run_id: str = "run1") -> str | None:
        return trino_output_folder(organization_id="org-uuid", team_id=7, saved_query_id=SAVED_QUERY_ID, run_id=run_id)

    @override_settings(DATA_MODELING_TRINO_OUTPUT_BUCKET_URL="")
    def test_the_copy_is_off_without_a_bucket_url(self) -> None:
        assert self._folder() is None

    @parameterized.expand([("bare", "s3://example-bucket"), ("trailing_slash", "s3://example-bucket/")])
    def test_each_run_writes_under_the_org_and_team_of_its_view(self, _name: str, url: str) -> None:
        with override_settings(DATA_MODELING_TRINO_OUTPUT_BUCKET_URL=url):
            assert self._folder() == f"s3://example-bucket/org_org-uuid/team_7/{SAVED_QUERY_ID.hex}/run1/"
            assert self._folder("run2") != self._folder("run1")
