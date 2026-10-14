from django.test import SimpleTestCase


class TestRetiredProductToursEndpoint(SimpleTestCase):
    def test_returns_an_empty_tour_list_that_released_sdks_can_cache(self) -> None:
        response = self.client.get(
            "/api/product_tours/?token=phc_example", headers={"origin": "https://www.example.com"}
        )

        assert response.status_code == 200
        assert response.json() == {"product_tours": []}
        assert response.has_header("Access-Control-Allow-Origin")
