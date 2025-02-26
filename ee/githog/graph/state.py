from typing import Optional, TypedDict, List

from githog.frameworks.config import GitHogFrameworkName

class FileChange(TypedDict):
    file_path: str
    new_content: str
    old_sha: Optional[str]

class AgentState(TypedDict):
    framework: Optional[GitHogFrameworkName]
    changes: List[FileChange]
    all_files: List[str]
    relevant_files: List[str]
    committed: bool
    branch: Optional[str]
    pr_url: Optional[str]