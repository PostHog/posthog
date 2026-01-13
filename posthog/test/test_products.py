from posthog.test.base import BaseTest

from posthog.schema import ProductKey

from posthog.products import Products


class TestProducts(BaseTest):
    def test_products_returns_list(self):
        products = Products.products()
        assert isinstance(products, list)

    def test_games_returns_list(self):
        games = Products.games()
        assert isinstance(games, list)

    def test_metadata_returns_list(self):
        metadata = Products.metadata()
        assert isinstance(metadata, list)

    def test_get_products_by_intent_returns_list(self):
        products = Products.get_products_by_intent(ProductKey.PRODUCT_ANALYTICS)
        assert isinstance(products, list)

    def test_get_products_by_category_returns_dict(self):
        products_by_category = Products.get_products_by_category()
        assert isinstance(products_by_category, dict)

    def test_get_product_paths_returns_list_of_strings(self):
        paths = Products.get_product_paths()
        assert isinstance(paths, list)
        assert all(isinstance(path, str) for path in paths)

    def test_get_products_by_category_has_expected_categories(self):
        products_by_category = Products.get_products_by_category()
        categories = set(products_by_category.keys())

        expected_categories = {"Analytics", "Behavior", "Features", "Tools", "Unreleased"}
        assert categories == expected_categories

    def test_get_products_by_category_each_category_has_list_of_strings(self):
        products_by_category = Products.get_products_by_category()
        for category, products in products_by_category.items():
            assert isinstance(category, str)
            assert isinstance(products, list)
            assert all(isinstance(product_path, str) for product_path in products)

    def test_get_products_by_category_products_in_category_exist(self):
        products_by_category = Products.get_products_by_category()
        all_product_paths = set(Products.get_product_paths())

        for category, product_paths in products_by_category.items():
            for product_path in product_paths:
                assert (
                    product_path in all_product_paths
                ), f"Product {product_path} in category {category} not found in all products"

    def test_reload_does_not_raise_error(self):
        try:
            Products.reload()
            assert True
        except Exception as e:
            raise AssertionError(f"Products.reload() raised an exception: {e}") from e
