from unittest.mock import patch

from clickhouse_driver.errors import ServerException

from posthog.test.base import APIBaseTest
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable


class TestTable(APIBaseTest):
    @patch(
        "posthog.warehouse.models.table.DataWarehouseTable.get_columns",
        return_value={"id": "String", "a_column": "String"},
    )
    def test_create(self, patch_get_columns):
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "whatever",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "credential": {
                    "access_key": "_accesskey",
                    "access_secret": "_accesssecret",
                },
                "format": "Parquet",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        response = response.json()

        table = DataWarehouseTable.objects.get()
        self.assertEqual(table.name, "whatever")
        self.assertEqual(table.columns, {"id": "String", "a_column": "String"})
        credentials = DataWarehouseCredential.objects.get()
        self.assertEqual(credentials.access_key, "_accesskey")
        self.assertEqual(credentials.access_secret, "_accesssecret")

    @patch("posthog.warehouse.models.table.DataWarehouseTable.get_columns")
    def test_credentialerror(self, patch_get_columns):
        patch_get_columns.side_effect = ServerException(
            message="""DB::Exception: The AWS Access Key Id you provided does not exist in our records.: Cannot extract table structure from Parquet format file. You can specify the structure manually. Stack trace:\n\n0. DB::Exception::Exception(std::__1::basic_string<char, std::__1::char_traits<char>, std::__1::allocator<char> > const&, int, bool) @ 0x8e25488 in /u""",
            code=499,
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_tables/",
            {
                "name": "whatever",
                "url_pattern": "https://your-org.s3.amazonaws.com/bucket/whatever.pqt",
                "credential": {
                    "access_key": "_accesskey",
                    "access_secret": "_accesssecret",
                },
                "format": "Parquet",
            },
        )
        self.assertEqual(response.status_code, 400, response.content)
        response = response.json()
