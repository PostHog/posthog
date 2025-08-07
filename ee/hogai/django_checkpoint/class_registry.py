import logging
from typing import Any, Optional
from pydantic import BaseModel
import importlib
import inspect
import os

logger = logging.getLogger(__name__)


class ClassRegistry:
    """
    Automatically discovers and registers Pydantic classes.
    """

    _cache: dict[str, type[BaseModel]]

    def __init__(self):
        # Scan all types.py files in ee.hogai
        self._scan_hogai_types()

        # Also scan posthog.schema for message types
        self._scan_module("posthog.schema")

        # Register langchain Pydantic classes that might be serialized
        self._register_langchain_classes()

        self._cache = {}

    def _scan_hogai_types(self):
        """Scan all types.py files within ee/hogai directory tree."""

        # Get the ee/hogai directory path
        ee_hogai_path = os.path.join(os.path.dirname(__file__), "..", "..")
        ee_hogai_path = os.path.abspath(ee_hogai_path)

        # Walk through all directories in ee/hogai
        for root, _, files in os.walk(ee_hogai_path):
            if "types.py" in files:
                # Convert file path to module path
                rel_path = os.path.relpath(root, os.path.dirname(ee_hogai_path))
                module_path = rel_path.replace(os.sep, ".") + ".types"

                # Skip test directories
                if "test" in module_path:
                    continue

                try:
                    self._scan_module(module_path)
                except Exception as e:
                    logger.warning(f"Could not scan {module_path}: {e}")

    def _scan_module(self, module_name: str):
        """Scan a module for Pydantic BaseModel classes."""
        try:
            module = importlib.import_module(module_name)
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and issubclass(obj, BaseModel):
                    # Only register if not already present
                    if name not in self._cache:
                        self._cache[name] = obj
        except ImportError as e:
            logger.warning(f"Could not import module {module_name}: {e}")

    def _register_langchain_classes(self):
        """Automatically register all Pydantic classes from langchain modules."""

        # List of langchain modules that commonly contain Pydantic models
        langchain_modules = [
            "langchain_core.agents",
            "langchain_core.messages",
            "langchain_core.outputs",
            "langchain_core.documents",
            "langchain_core.prompt_values",
            "langchain_core.tools",
            "langchain_core.callbacks",
            "langchain_core.chat_history",
        ]

        for module_name in langchain_modules:
            try:
                module = importlib.import_module(module_name)
                # Scan all members of the module
                for name, obj in inspect.getmembers(module):
                    # Register if it's a Pydantic BaseModel class (not an instance)
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, BaseModel)
                        and obj.__module__.startswith("langchain")  # Only langchain classes
                        and not name.startswith("_")
                    ):  # Skip private classes
                        # Use the simple class name as key (e.g., "AIMessage" not "langchain_core.messages.AIMessage")
                        class_name = obj.__name__
                        if class_name not in self._cache:
                            self._cache[class_name] = obj

            except ImportError:
                # Module not available, skip it
                continue
            except Exception as e:
                logger.warning(f"Could not scan langchain module {module_name}: {e}")

    def get_class(self, class_name: str) -> Optional[type[BaseModel]]:
        """
        Get a class by name, auto-discovering if needed.

        Args:
            class_name: The name of the class (e.g., "AssistantState")

        Returns:
            The class if found, None otherwise
        """
        # Check cache first
        if class_name in self._cache:
            return self._cache[class_name]
        return None

    def construct(self, class_name: str, data: dict[str, Any]) -> Any:
        """
        Construct an object by class name.

        - Exact class name match only
        - Recursive construction for nested Pydantic models
        - Fallback to dict if class not found

        Args:
            class_name: Name of the class to construct
            data: Data to construct the object with

        Returns:
            Constructed object or original dict if class not found
        """
        cls = self.get_class(class_name)

        if cls is None:
            # Not a Pydantic class we know about - return as dict
            return data

        try:
            # Remove _type from data if it exists (we already know the type)
            data_copy = data.copy()
            data_copy.pop("_type", None)

            # Recursively construct nested Pydantic objects
            processed_data = self._process_nested_objects(data_copy)

            # Let Pydantic handle the construction with its own validation/defaults
            return cls(**processed_data)

        except Exception as e:
            logger.warning(f"Failed to construct {class_name}: {e}")
            return data

    def _process_nested_objects(self, data: Any) -> Any:
        """
        Recursively process data to construct nested Pydantic objects.
        """
        if isinstance(data, dict):
            # Check if this dict represents a Pydantic object
            if "_type" in data:
                # Make a copy to avoid modifying original
                data_copy = data.copy()
                obj_type = data_copy.pop("_type")
                nested_obj = self.construct(obj_type, data_copy)
                if nested_obj is not data_copy:  # Successfully constructed
                    return nested_obj
                # Failed, return original data with _type
                return data

            # Process all values recursively
            return {k: self._process_nested_objects(v) for k, v in data.items()}

        elif isinstance(data, list):
            # Process all items in the list
            return [self._process_nested_objects(item) for item in data]

        else:
            # Primitive value, return as-is
            return data


class_registry = ClassRegistry()
