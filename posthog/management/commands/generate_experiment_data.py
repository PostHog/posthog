from datetime import datetime, timedelta
import logging
import random
import secrets
import time
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

        # TODO: actually implement a seed
        seed = options.get("seed") or secrets.token_hex(16)

        if not experiment_id:
            raise ValueError("Experiment ID is required")

        # TODO: this can be a config file taken as an argument
        experiment_config = {
            "experiment_id": experiment_id,
            "seed": seed,
            "number_of_users": 1000,
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

        variants = list(experiment_config["variants"].keys())
        variant_counts = {variant: 0 for variant in variants}
        for _ in range(experiment_config["number_of_users"]):
            variant = random.choices(
                variants,
                weights=[v["weight"] for v in experiment_config["variants"].values()],
            )[0]
            variant_counts[variant] += 1
            distinct_id = uuid.uuid4()
            random_timestamp = random.uniform(
                experiment_config["start_timestamp"], experiment_config["end_timestamp"] - timedelta(hours=1)
            )
            posthoganalytics.capture(
                distinct_id=distinct_id,
                event="$feature_flag_called",
                timestamp=random_timestamp,
                properties={
                    "$feature_flag": experiment_config["experiment_id"],
                    f"$feature/{experiment_config['experiment_id']}": variant,
                },
            )

            for action in experiment_config["variants"][variant]["actions"]:
                if random.random() < action["probability"]:
                    posthoganalytics.capture(
                        distinct_id=distinct_id,
                        event=action["event"],
                        timestamp=random_timestamp + timedelta(minutes=1),
                    )

        logging.info(f"Generated data for {experiment_config['experiment_id']} with seed {seed}")
        logging.info(f"Variant counts: {variant_counts}")

        # TODO: need to figure out how to wait for the data to be flushed. shutdown() doesn't work as expected.
        time.sleep(10)
        posthoganalytics.shutdown()
