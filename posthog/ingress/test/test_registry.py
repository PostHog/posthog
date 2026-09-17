from django.test import SimpleTestCase

from posthog.ingress.contracts import ProviderSpec, WebhookConsumer, WebhookDelivery
from posthog.ingress.dispatch.loading import get_consumer_registry, reset_consumer_registry
from posthog.ingress.dispatch.registry import ConsumerRegistry, RegistryError
from posthog.ingress.github.provider import SPECS as GITHUB_SPECS

GITHUB = ProviderSpec(provider="github", app="posthog", event_types=frozenset({"pull_request", "push"}))
STAMPHOG = ProviderSpec(provider="github", app="stamphog", event_types=frozenset({"pull_request"}))


def _noop(delivery: WebhookDelivery) -> None:
    return None


def _consumer(
    name: str,
    *,
    provider: str = "github",
    app: str = "posthog",
    event_types: frozenset[str] = frozenset({"pull_request"}),
) -> WebhookConsumer:
    return WebhookConsumer(name=name, provider=provider, app=app, event_types=event_types, handler=_noop)


class TestConsumerRegistry(SimpleTestCase):
    def test_groups_consumers_by_event_type_in_name_order(self) -> None:
        registry = ConsumerRegistry(
            providers=[GITHUB],
            consumers=[
                _consumer("loops", event_types=frozenset({"pull_request", "push"})),
                _consumer("tasks_pr_backstop"),
                _consumer("conversations", event_types=frozenset({"push"})),
            ],
        )

        self.assertEqual(
            [consumer.name for consumer in registry.consumers_for(provider="github", app="posthog", event_type="push")],
            ["conversations", "loops"],
        )
        self.assertEqual(
            [
                consumer.name
                for consumer in registry.consumers_for(provider="github", app="posthog", event_type="pull_request")
            ],
            ["loops", "tasks_pr_backstop"],
        )
        self.assertEqual(registry.consumers_for(provider="github", app="posthog", event_type="issues"), ())

    def test_duplicate_name_within_a_provider_is_refused(self) -> None:
        with self.assertRaises(RegistryError) as caught:
            ConsumerRegistry(
                providers=[GITHUB, STAMPHOG],
                consumers=[_consumer("loops"), _consumer("loops", app="stamphog")],
            )
        self.assertIn("Duplicate consumer name", str(caught.exception))

    def test_unknown_provider_app_is_refused(self) -> None:
        with self.assertRaises(RegistryError) as caught:
            ConsumerRegistry(providers=[GITHUB], consumers=[_consumer("loops", app="gitlab")])
        self.assertIn("unknown provider app", str(caught.exception))

    def test_event_type_the_provider_does_not_declare_is_refused(self) -> None:
        with self.assertRaises(RegistryError) as caught:
            ConsumerRegistry(
                providers=[GITHUB],
                consumers=[_consumer("loops", event_types=frozenset({"pull_request", "deployment"}))],
            )
        self.assertIn("deployment", str(caught.exception))

    def test_the_real_registry_builds_from_every_incarnation_and_product(self) -> None:
        reset_consumer_registry()
        self.addCleanup(reset_consumer_registry)

        registry = get_consumer_registry()

        self.assertEqual(
            [
                consumer.name
                for consumer in registry.consumers_for(provider="github", app="posthog", event_type="installation")
            ],
            ["installation_lifecycle"],
        )

    def test_no_github_consumer_opts_into_regional_forwarding(self) -> None:
        # Each region runs its own GitHub App, with its own webhook URL and its own secret, so a
        # replayed delivery can only fail the other region's signature check. The forward lane
        # keys off `ownership` alone, so leaving it unset is what keeps GitHub out of it.
        reset_consumer_registry()
        self.addCleanup(reset_consumer_registry)

        registry = get_consumer_registry()

        for spec in GITHUB_SPECS:
            for event_type in sorted(spec.event_types):
                for consumer in registry.consumers_for(provider="github", app=spec.app, event_type=event_type):
                    self.assertIsNone(consumer.ownership, f"{consumer.name} would forward {event_type} deliveries")

    def test_same_name_on_two_apps_is_kept_apart_when_providers_differ(self) -> None:
        slack = ProviderSpec(provider="slack", app="supporthog", event_types=frozenset({"message"}))
        registry = ConsumerRegistry(
            providers=[GITHUB, slack],
            consumers=[
                _consumer("conversations"),
                _consumer("conversations", provider="slack", app="supporthog", event_types=frozenset({"message"})),
            ],
        )

        self.assertEqual(
            len(registry.consumers_for(provider="slack", app="supporthog", event_type="message")),
            1,
        )
