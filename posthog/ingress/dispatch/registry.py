"""The validated consumer registry.

Registration order is unspecified by contract. The implementation iterates consumers sorted
by name so logs and metrics read the same way on every delivery, and so a product cannot make
its consumer run first by registering earlier.
"""

from collections import defaultdict
from collections.abc import Sequence

from posthog.ingress.contracts import ProviderSpec, WebhookConsumer


class RegistryError(Exception):
    """A consumer declaration no provider incarnation can serve."""


class ConsumerRegistry:
    """Consumers grouped by (provider, app, event type), validated once at build.

    Validation is fail-closed on purpose: a consumer that names a provider nobody
    declares, or an event type the provider never sends, would otherwise sit there
    looking registered and never run.
    """

    def __init__(self, *, providers: Sequence[ProviderSpec], consumers: Sequence[WebhookConsumer]) -> None:
        specs = {(spec.provider, spec.app): spec for spec in providers}
        names_by_provider: dict[str, set[str]] = defaultdict(set)
        grouped: dict[tuple[str, str, str], list[WebhookConsumer]] = defaultdict(list)

        for consumer in sorted(consumers, key=lambda registered: registered.name):
            spec = specs.get((consumer.provider, consumer.app))
            if spec is None:
                raise RegistryError(
                    f"Consumer {consumer.name!r} registers for unknown provider app "
                    f"{consumer.provider!r}/{consumer.app!r}"
                )
            # Scoped per provider rather than per app, because the dedup cache key carries
            # the provider and the name but not the app.
            if consumer.name in names_by_provider[consumer.provider]:
                raise RegistryError(f"Duplicate consumer name {consumer.name!r} for provider {consumer.provider!r}")
            names_by_provider[consumer.provider].add(consumer.name)

            undeclared = consumer.event_types - spec.event_types
            if undeclared:
                raise RegistryError(
                    f"Consumer {consumer.name!r} registers for event types {sorted(undeclared)} that "
                    f"{consumer.provider!r}/{consumer.app!r} does not declare"
                )
            for event_type in sorted(consumer.event_types):
                grouped[(consumer.provider, consumer.app, event_type)].append(consumer)

        self._declared: frozenset[tuple[str, str]] = frozenset(specs)
        self._grouped: dict[tuple[str, str, str], tuple[WebhookConsumer, ...]] = {
            key: tuple(matched) for key, matched in grouped.items()
        }

    def declares(self, *, provider: str, app: str) -> bool:
        """Whether any incarnation declares this provider app.

        A delivery for an app nobody declares can never match a consumer, so the dispatcher
        reports it rather than answering a healthy-looking receipt to nothing.
        """
        return (provider, app) in self._declared

    def consumers_for(self, *, provider: str, app: str, event_type: str) -> tuple[WebhookConsumer, ...]:
        return self._grouped.get((provider, app, event_type), ())
