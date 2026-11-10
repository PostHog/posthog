"""What a provider's subject lookup returns, kept apart from the registry so lookups can import it."""

from __future__ import annotations

from collections.abc import Callable

from posthog.dataclasses import frozen


@frozen
class ResolvedWorkloadSubject:
    """A workload's immutable subject, found from the name a person typed."""

    subject: str
    # The provider's canonical spelling of the name, which the token carries exactly.
    subject_name: str
    # Where PostHog found it, for the UI, for example "your GitHub integration".
    found_via: str


class WorkloadSubjectNotFound(Exception):
    """The provider has no workload by that name that PostHog can see. The message is shown to the user."""


class WorkloadSubjectLookupUnavailable(Exception):
    """The provider didn't answer, or limited PostHog's requests. The message is shown to the user."""


SubjectResolver = Callable[[int, str], ResolvedWorkloadSubject]
