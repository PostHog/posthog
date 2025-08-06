import logging
from typing import Any, Optional
from pydantic import BaseModel
import importlib
import inspect

logger = logging.getLogger(__name__)


class ClassRegistry:
    """
    Automatically discovers and registers Pydantic classes.
    """

    _cache: dict[str, type[BaseModel]] = {}
    _modules_to_scan = [
        "ee.hogai.utils.types",  # All state types
        "posthog.schema",  # All message types
    ]

    def __init__(self):
        for module_name in self._modules_to_scan:
            module = importlib.import_module(module_name)
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and issubclass(obj, BaseModel):
                    self._cache[name] = obj

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
