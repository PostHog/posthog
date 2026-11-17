import os
import gzip
import json
import tempfile
from pathlib import Path

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api import cli_catalog

URL = "/api/cli/catalog.json"


class TestCliCatalog(SimpleTestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "cli-catalog.json"
        patcher = patch.object(cli_catalog, "CLI_CATALOG_JSON", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, catalog: dict, modified: int) -> None:
        self.path.write_text(json.dumps(catalog))
        os.utime(self.path, (modified, modified))

    @parameterized.expand([("gzip", "gzip, br", "gzip"), ("plain", "br", None)])
    def test_serves_the_built_catalog_to_an_anonymous_client(self, _name, accept, encoding) -> None:
        self.write({"schemaVersion": 1, "tools": []}, modified=1_000)

        response = self.client.get(URL, headers={"accept-encoding": accept})

        assert response.status_code == 200
        assert response.get("Content-Encoding") == encoding
        assert "public" in response["Cache-Control"]
        assert "Accept-Encoding" in response["Vary"]
        body = gzip.decompress(response.content) if encoding else response.content
        assert json.loads(body) == {"schemaVersion": 1, "tools": []}

    def test_answers_a_known_etag_with_not_modified_and_a_changed_file_with_the_new_catalog(self) -> None:
        self.write({"schemaVersion": 1, "tools": []}, modified=1_000)
        etag = self.client.get(URL)["ETag"]

        unchanged = self.client.get(URL, headers={"if-none-match": etag})
        self.write({"schemaVersion": 1, "tools": [{"name": "new-tool"}]}, modified=2_000)
        changed = self.client.get(URL, headers={"if-none-match": etag})

        assert unchanged.status_code == 304
        assert changed.status_code == 200
        assert changed["ETag"] != etag
        assert json.loads(changed.content)["tools"] == [{"name": "new-tool"}]

    def test_names_the_build_command_when_no_catalog_was_built(self) -> None:
        response = self.client.get(URL)

        assert response.status_code == 404
        assert cli_catalog.BUILD_COMMAND in response.json()["detail"]
