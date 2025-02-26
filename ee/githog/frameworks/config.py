from enum import Enum
from typing import Callable

from pydantic import BaseModel


class GitHogFrameworkName(Enum):
    NEXTJS_APP_ROUTER = "NEXTJS_APP_ROUTER"
    NEXTJS_PAGES_ROUTER = "NEXTJS_PAGES_ROUTER"


class GitHogFrameworkConfig(BaseModel):
    name: GitHogFrameworkName
    installation_instructions: str
    pr_instructions: str
    detect: Callable[[list[str]], bool]
    filter_patterns: list[str]
    include_patterns: list[str]
    ignore_patterns: list[str]
    create_patterns: list[str]
    
