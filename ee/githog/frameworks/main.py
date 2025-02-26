from .nextjs_pages_router import NEXTJS_PAGES_ROUTER_CONFIG
from .config import GitHogFrameworkConfig, GitHogFrameworkName
from .nextjs_app_router import NEXTJS_APP_ROUTER_CONFIG
from githog.file_utils import matches_any_pattern


GITHOG_FRAMEWORK_CONFIGS = {
    NEXTJS_APP_ROUTER_CONFIG.name: NEXTJS_APP_ROUTER_CONFIG,
    NEXTJS_PAGES_ROUTER_CONFIG.name: NEXTJS_PAGES_ROUTER_CONFIG,
}

class GitHogFramework:

    config: GitHogFrameworkConfig

    def __init__(self, config: GitHogFrameworkConfig):
        self.config = config

    def __repr__(self):
        return f"<GitHogFrameworkConfig name={self.config.name}>"
    
    def is_relevant(self, path: str) -> bool:
        if matches_any_pattern(path, self.config.include_patterns):
            return True
        if matches_any_pattern(path, self.config.ignore_patterns):
            return False
        
        return matches_any_pattern(path, self.config.filter_patterns)

def get_framework(name: GitHogFrameworkName) -> GitHogFramework:
    config = GITHOG_FRAMEWORK_CONFIGS[name]

    if config is None:
        raise ValueError(f"No config found for framework {name}")

    return GitHogFramework(config)