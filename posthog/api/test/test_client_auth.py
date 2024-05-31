from rest_framework import status

from posthog.test.base import APIBaseTest


class TestAuthenticationCli(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.cli_client = self.client_class()
        assert self.cli_client.get("/api/client_authorization").status_code == status.HTTP_401_UNAUTHORIZED

    def do_successful_flow(self):
        res = self.client.post("/api/client_authorization/start")
        assert res.status_code == status.HTTP_200_OK
        assert res.json()["code"]
        code = res.json()["code"]

        assert self.cli_client.get(f"/api/client_authorization/check?code={code}").json()["status"] == "pending"

        res = self.client.get(f"/api/client_authorization/?code={code}")
        assert res.status_code == status.HTTP_200_OK
        assert res.json().get("code")
        assert res.json().get("verification")

        assert self.cli_client.get(f"/api/client_authorization/check?code={code}").json()["status"] == "pending"

        res = self.client.post(
            "/api/client_authorization/confirm", data={"code": code, "verification": res.json()["verification"]}
        )
        assert res.status_code == status.HTTP_200_OK, res.json()
        assert res.json()["status"] == "authorized"

        res = self.cli_client.get(f"/api/client_authorization/check?code={code}").json()
        assert res["status"] == "authorized"
        assert res["access_token"]

        # Check the second time it is gone
        assert self.cli_client.get(f"/api/client_authorization/check?code={code}").json()["status"] == "missing"

        return res["access_token"]

    def test_standard_flow(self):
        self.do_successful_flow()

    def test_can_call_api_with_created_token(self):
        access_token = self.do_successful_flow()
        res = self.cli_client.get("/api/users/@me", HTTP_AUTHORIZATION=f"Bearer {access_token}")

        assert res.status_code == status.HTTP_200_OK
