# posthog/models/file_system/file_system_representation.py

from dataclasses import dataclass
from typing import Any


@dataclass
class FileSystemRepresentation:
    """
    Defines the minimal data needed to create/update a FileSystem entry:
      - base_folder
      - type
      - ref
      - name
      - href
      - meta
      - should_delete: if True, we remove the entry instead of creating/updating
    """

    base_folder: str
    type: str
    ref: str
    name: str
    href: str
    meta: dict[str, Any]
    should_delete: bool = False
