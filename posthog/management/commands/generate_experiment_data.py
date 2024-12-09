from datetime import datetime, timedelta
import logging
import random
import secrets
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand
import posthoganalytics


logging.getLogger("kafka").setLevel(logging.ERROR)  # Hide kafka-python's logspam


class Command(BaseCommand):
    help = "Generate experiment data"

    def add_arguments(self, parser):
        parser.add_argument("--experiment-id", type=str, help="Experiment ID")
        parser.add_argument("--seed", type=str, help="Simulation seed for deterministic output")

    def handle(self, *args, **options):
        # Make sure this runs in development environment only
        if not settings.DEBUG:
            raise ValueError("This command should only be run in development! DEBUG must be True.")

        experiment_id = options.get("experiment_id")
        seed = options.get("seed") or secrets.token_hex(16)

        if not experiment_id:
            raise ValueError("Experiment ID is required")

        experiment_config = {
            "experiment_id": experiment_id,
            "seed": seed,
            "number_of_users": 10,
            "start_timestamp": datetime.now() - timedelta(days=7),
            "end_timestamp": datetime.now(),
            "variants": {
                "control": {
                    "weight": 0.5,
                    "actions": [
                        {"event": "$pageview", "probability": 0.75},
                    ],
                },
                "test": {
                    "weight": 0.5,
                    "actions": [
                        {"event": "$pageview", "probability": 1},
                    ],
                },
            },
        }

        for _ in range(experiment_config["number_of_users"]):
            variant = random.choices(
                list(experiment_config["variants"].keys()),
                weights=[v["weight"] for v in experiment_config["variants"].values()],
            )[0]
            distinct_id = uuid.uuid4()
            random_timestamp = random.uniform(
                experiment_config["start_timestamp"], experiment_config["end_timestamp"] - timedelta(hours=1)
            )
            print(f"Generating data for user {distinct_id} at {random_timestamp} with variant {variant}")
            posthoganalytics.capture(
                distinct_id=distinct_id,
                event="$feature_flag_called",
                timestamp=random_timestamp,
                properties={
                    "feature_flag": experiment_config["experiment_id"],
                    f"feature/{experiment_config['experiment_id']}": variant,
                },
            )

            for action in experiment_config["variants"][variant]["actions"]:
                if random.random() < action["probability"]:
                    print(f"Generating data for user {distinct_id} at {random_timestamp + timedelta(minutes=1)} with event {action['event']}")
                    posthoganalytics.capture(
                        distinct_id=distinct_id,
                        event=action["event"],
                        timestamp=random_timestamp + timedelta(minutes=1),
                    )
