from posthog.test.base import BaseTest

from posthog.scopes import EXPOSED_SCOPE_OBJECTS


class TestOAuthScopeReference(BaseTest):
    def test_lists_exposed_scopes_publicly_with_a_shared_cache(self) -> None:
        response = self.client.get("/oauth/scopes/")

        assert response.status_code == 200
        assert response["Cache-Control"].startswith("public")
        assert response["Access-Control-Allow-Origin"] == "*"

        objects = {entry["object"]: entry for entry in response.json()["objects"]}
        assert sorted(objects) == sorted(EXPOSED_SCOPE_OBJECTS)
        assert {a["scope"]: a["oauth"] for a in objects["llm_gateway"]["actions"]} == {"llm_gateway:read": False}
        assert objects["survey"]["write_requires"]["scope"] == "feature_flag:write"
