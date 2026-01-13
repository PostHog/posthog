import json
from collections import defaultdict
from pathlib import Path
from typing import Optional

from django.conf import settings

from posthog.schema import ProductItem, ProductKey, ProductsData


class Products:
    """Singleton class to access products.json data with automatic reloading."""

    _instance: Optional["Products"] = None
    _data: Optional[ProductsData] = None
    _file_path: Optional[Path] = None

    def __new__(cls) -> "Products":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._file_path = cls._get_products_json_path()
            cls._instance._load_data()
        return cls._instance

    @staticmethod
    def _get_products_json_path() -> Path:
        """Get the path to products.json relative to the project root."""
        base_dir = Path(settings.BASE_DIR)
        return base_dir / "frontend" / "src" / "products.json"

    def _load_data(self) -> None:
        """Load products.json data from disk and validate with Pydantic."""
        if self._file_path is None or not self._file_path.exists():
            raise FileNotFoundError(
                f"products.json not found at {self._file_path}. " "Generate it by running: hogli build:products"
            )

        with open(self._file_path) as f:
            data = json.load(f)
        self._data = ProductsData.model_validate(data)

    @staticmethod
    def reload() -> None:
        """Reload products.json data from disk."""
        instance = Products()
        instance._load_data()

    @staticmethod
    def _get_data() -> ProductsData:
        """Get the loaded data, loading if necessary."""
        instance = Products()
        if instance._data is None:
            instance._load_data()

        assert instance._data is not None
        return instance._data

    @staticmethod
    def products() -> list[ProductItem]:
        """Get the list of products."""
        return Products._get_data().products

    @staticmethod
    def games() -> list[ProductItem]:
        """Get the list of games."""
        return Products._get_data().games

    @staticmethod
    def metadata() -> list[ProductItem]:
        """Get the list of metadata items."""
        return Products._get_data().metadata

    @staticmethod
    def get_product_paths() -> list[str]:
        """Get all product paths."""
        return [product.path for product in Products.products()]

    @staticmethod
    def get_products_by_intent(intent: ProductKey) -> list[ProductItem]:
        """Get all products that the intent is associated with."""
        return [product for product in Products.products() if intent in product.intents]

    @staticmethod
    def get_products_by_category() -> dict[str, list[str]]:
        """Get product mappings grouped by category."""
        products_by_category: dict[str, list[str]] = defaultdict(list)
        for product in Products.products():
            category = product.category or "Other"
            products_by_category[category].append(product.path)
        return dict(products_by_category)
