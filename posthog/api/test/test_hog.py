from posthog.test.base import APIBaseTest

from rest_framework import status


class TestHogAPI(APIBaseTest):
    def test_compiles_valid_hog(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.id}/hog/", {"hog": "return 1 + 1;"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertIn("bytecode", response.json())

    def test_invalid_hog_returns_400_not_server_error(self) -> None:
        # Half-finished Hog typed into the debug console must return a graceful 400,
        # not escape as an uncaught SyntaxError captured as a server exception.
        response = self.client.post(f"/api/projects/{self.team.id}/hog/", {"hog": "(if (true) {"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertIn("error", response.json())
