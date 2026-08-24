import json
import importlib
import importlib.util
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Optional

from django.apps import apps
from django.conf import settings

from posthog.schema_enums import ProductItemCategory, ProductKey

# Products are Django apps under `products/`, installed as `products.<name>.backend`.
PRODUCT_MODULE_PREFIX = "products."


def is_product_module(module_name: str) -> bool:
    """Whether a module path lives inside a product, e.g. `products.logs.backend.api`."""
    return module_name.startswith(PRODUCT_MODULE_PREFIX)


def product_app_names() -> list[str]:
    """Names of the installed product apps, e.g. `products.logs.backend`."""
    return [app_config.name for app_config in apps.get_app_configs() if is_product_module(app_config.name)]


def load_product_modules(submodule: str) -> Iterator[ModuleType]:
    """Import `<product app>.<submodule>` for every product that has one.

    How core picks up per-product declarations (`routes`, `data_freshness`, ...) without a
    hand-maintained list. `find_spec` rather than try/except so a real ImportError inside a
    product's module surfaces instead of reading as "this product doesn't have one".

    Products are imported dynamically here, so the core->product edges are invisible to import
    tooling (tach/grimp). Accepted on purpose, as the alternative duplicates PRODUCTS_APPS.
    """
    for app_name in product_app_names():
        module_name = f"{app_name}.{submodule}"
        if importlib.util.find_spec(module_name) is None:
            continue
        yield importlib.import_module(module_name)


# This module loads at django.setup() via the file-system product list; posthog.schema
# (the pydantic models) is runtime-imported only when products.json is actually loaded.
if TYPE_CHECKING:
    from posthog.schema import ProductItem, ProductsData


class Products:
    """Singleton class to access products.json data with automatic reloading."""

    _instance: Optional["Products"] = None
    _data: Optional["ProductsData"] = None
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
        from posthog.schema import ProductsData  # noqa: PLC0415

        if self._file_path is None or not self._file_path.exists():
            raise FileNotFoundError(
                f"products.json not found at {self._file_path}. Generate it by running: hogli build:products"
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
    def _get_data() -> "ProductsData":
        """Get the loaded data, loading if necessary."""
        instance = Products()
        if instance._data is None:
            instance._load_data()

        assert instance._data is not None
        return instance._data

    @staticmethod
    def products() -> list["ProductItem"]:
        """Get the list of products."""
        return Products._get_data().products

    @staticmethod
    def games() -> list["ProductItem"]:
        """Get the list of games."""
        return Products._get_data().games

    @staticmethod
    def metadata() -> list["ProductItem"]:
        """Get the list of metadata items."""
        return Products._get_data().metadata

    @staticmethod
    def get_product_paths() -> list[str]:
        """Get all product paths."""
        return [product.path for product in Products.products()]

    @staticmethod
    def get_products_by_intent(intent: ProductKey) -> list["ProductItem"]:
        """Get all products that the intent is associated with."""
        return [product for product in Products.products() if intent in product.intents]

    @staticmethod
    def get_products_by_category() -> dict[ProductItemCategory, list[str]]:
        """Get product mappings grouped by category."""
        products_by_category: dict[ProductItemCategory, list[str]] = defaultdict(list)
        for product in Products.products():
            if product.category is not None:
                products_by_category[product.category].append(product.path)
        return dict(products_by_category)
