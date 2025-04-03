# posthog/models/file_system/file_system_representation.py

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class FileSystemRepresentation:
    """
    Defines the minimal data needed to create/update a FileSystem entry:
    """

    project_id: int
    base_folder: str
    type: str
    ref: str
    name: str
    href: str
    meta: dict[str, Any]
    should_delete: bool = False  # if True, we remove the entry instead of creating/updating
    # Team ID is optional and indicates this is an environment specific resource
    team_id: Optional[int] = None
