from django.core.management.base import BaseCommand

from products.customer_analytics.backend.consumers.person_property_update_consumer import PersonPropertyUpdateConsumer


class Command(BaseCommand):
    help = "Consume warehouse person-property $set intents and send them to capture, rate-limited."

    def handle(self, *args, **options) -> None:
        PersonPropertyUpdateConsumer().run()
