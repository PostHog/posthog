# posthog/models/file_system/file_system_representation.py

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class FileSystemRepresentation:
    """
    Defines the minimal data needed to create/update a FileSystem entry:
    """

    base_folder: str
    type: str
    ref: str
    name: str
    href: str
    meta: dict[str, Any]
    should_delete: bool = False  # if True, we remove the entry instead of creating/updating
    # Either project_id or team_id must be set
    project_id: Optional[int] = None
    team_id: Optional[int] = None
