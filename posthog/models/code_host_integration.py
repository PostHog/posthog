"""Provider-neutral adapter layer over ``Integration`` for code hosts.

No Django model lives here: each adapter wraps an existing ``Integration`` row
behind the shared ``CodeHostIntegration`` protocol and translates its
provider-specific errors into ``CodeHostIntegrationError``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from urllib.parse import quote

from posthog.egress.azure_devops import AZURE_DEVOPS_BASE_URL
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import (
    AzureDevOpsIntegration,
    AzureDevOpsIntegrationError,
    GitHubIntegration,
    Integration,
)


class UnsupportedCodeHostIntegrationError(Exception):
    pass


class CodeHostIntegrationError(Exception):
    pass


@contextmanager
def _as_code_host_error(*provider_errors: type[Exception]) -> Iterator[None]:
    try:
        yield
    except provider_errors as error:
        raise CodeHostIntegrationError(str(error)) from error


@dataclass(frozen=True)
class CodeHostRepository:
    id: str
    name: str
    full_name: str
    provider: str
    default_branch: str | None = None
    can_push: bool | None = None

    def as_dict(self) -> dict[str, str | bool | None]:
        return asdict(self)


@dataclass(frozen=True)
class CodeHostRepositoryPage:
    repositories: list[CodeHostRepository]
    has_more: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "repositories": [repository.as_dict() for repository in self.repositories],
            "has_more": self.has_more,
        }


class CodeHostIntegration(Protocol):
    def list_repositories(self, *, search: str, limit: int, offset: int) -> CodeHostRepositoryPage: ...

    def get_default_branch(self, repository: str) -> str | None: ...

    def create_branch(self, repository: str, branch_name: str, base_branch: str | None = None) -> dict[str, Any]: ...

    def create_pull_request(
        self,
        repository: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str | None = None,
    ) -> dict[str, Any]: ...

    def clone_url(self, repository: str) -> str: ...


class GitHubCodeHostIntegration:
    def __init__(self, integration: Integration) -> None:
        self.github = GitHubIntegration(integration)

    def list_repositories(self, *, search: str, limit: int, offset: int) -> CodeHostRepositoryPage:
        with _as_code_host_error(GitHubIntegrationError):
            repositories, has_more = self.github.list_cached_repositories(search=search, limit=limit, offset=offset)
        return CodeHostRepositoryPage(
            repositories=[
                CodeHostRepository(
                    id=str(repository["id"]),
                    name=repository["name"],
                    full_name=repository["full_name"],
                    provider=Integration.IntegrationKind.GITHUB.value,
                    default_branch=repository.get("default_branch"),
                    can_push=repository.get("can_push"),
                )
                for repository in repositories
            ],
            has_more=has_more,
        )

    def get_default_branch(self, repository: str) -> str:
        with _as_code_host_error(GitHubIntegrationError):
            return self.github.get_default_branch(repository)

    def create_branch(self, repository: str, branch_name: str, base_branch: str | None = None) -> dict[str, Any]:
        with _as_code_host_error(GitHubIntegrationError):
            return self.github.create_branch(self._repository_name(repository), branch_name, base_branch)

    def create_pull_request(
        self,
        repository: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str | None = None,
    ) -> dict[str, Any]:
        with _as_code_host_error(GitHubIntegrationError):
            return self.github.create_pull_request(
                self._repository_name(repository), title, body, head_branch, base_branch
            )

    def clone_url(self, repository: str) -> str:
        full_name = repository if "/" in repository else f"{self.github.organization()}/{repository}"
        return f"https://github.com/{full_name}.git"

    def _repository_name(self, repository: str) -> str:
        prefix = f"{self.github.organization()}/"
        return repository.removeprefix(prefix)


class AzureDevOpsCodeHostIntegration:
    def __init__(self, integration: Integration) -> None:
        with _as_code_host_error(AzureDevOpsIntegrationError):
            self.azure_devops = AzureDevOpsIntegration(integration)

    def list_repositories(self, *, search: str, limit: int, offset: int) -> CodeHostRepositoryPage:
        search_query = search.strip().casefold()
        with _as_code_host_error(AzureDevOpsIntegrationError):
            provider_repositories = self.azure_devops.list_repositories()
        repositories = []
        for repository in provider_repositories:
            full_name = f"{self.azure_devops.organization}/{self.azure_devops.project}/{repository['name']}"
            if search_query and search_query not in full_name.casefold():
                continue
            repositories.append(
                CodeHostRepository(
                    id=str(repository["id"]),
                    name=repository["name"],
                    full_name=full_name,
                    provider=Integration.IntegrationKind.AZURE_DEVOPS.value,
                    default_branch=repository.get("default_branch"),
                )
            )
        return CodeHostRepositoryPage(
            repositories=repositories[offset : offset + limit],
            has_more=len(repositories) > offset + limit,
        )

    def get_default_branch(self, repository: str) -> str | None:
        with _as_code_host_error(AzureDevOpsIntegrationError):
            return self.azure_devops.get_default_branch(self._repository_name(repository))

    def create_branch(self, repository: str, branch_name: str, base_branch: str | None = None) -> dict[str, Any]:
        with _as_code_host_error(AzureDevOpsIntegrationError):
            return self.azure_devops.create_branch(self._repository_name(repository), branch_name, base_branch)

    def create_pull_request(
        self,
        repository: str,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str | None = None,
    ) -> dict[str, Any]:
        with _as_code_host_error(AzureDevOpsIntegrationError):
            return self.azure_devops.create_pull_request(
                self._repository_name(repository), title, body, head_branch, base_branch
            )

    def clone_url(self, repository: str) -> str:
        repository_name = self._repository_name(repository)
        return (
            f"{AZURE_DEVOPS_BASE_URL}/{quote(self.azure_devops.organization)}/"
            f"{quote(self.azure_devops.project)}/_git/{quote(repository_name)}"
        )

    def _repository_name(self, repository: str) -> str:
        prefix = f"{self.azure_devops.organization}/{self.azure_devops.project}/"
        return repository.removeprefix(prefix)


def code_host_integration_for(integration: Integration) -> CodeHostIntegration:
    if integration.kind == Integration.IntegrationKind.GITHUB:
        return GitHubCodeHostIntegration(integration)
    if integration.kind == Integration.IntegrationKind.AZURE_DEVOPS:
        return AzureDevOpsCodeHostIntegration(integration)
    raise UnsupportedCodeHostIntegrationError(
        f"Integration {integration.id} is not a supported code host (kind={integration.kind!r})"
    )
