from datetime import datetime, timedelta
import logging
import random
import time
import uuid
import json

from django.conf import settings
from django.core.management.base import BaseCommand
import posthoganalytics
from pydantic import BaseModel, ValidationError


class ActionConfig(BaseModel):
    event: str
    probability: float
    count: int = 1
    required_for_next: bool = False

    def model_post_init(self, __context) -> None:
        if self.required_for_next and self.count > 1:
            raise ValueError("'required_for_next' cannot be used with 'count' greater than 1")


class VariantConfig(BaseModel):
    weight: float
    actions: list[ActionConfig]


class ExperimentConfig(BaseModel):
    number_of_users: int
    start_timestamp: datetime
    end_timestamp: datetime
    variants: dict[str, VariantConfig]


def get_default_funnel_experiment_config() -> ExperimentConfig:
    return ExperimentConfig(
        number_of_users=2000,
        start_timestamp=datetime.now() - timedelta(days=7),
        end_timestamp=datetime.now(),
        variants={
            "control": VariantConfig(
                weight=0.5,
                actions=[
                    ActionConfig(event="signup started", probability=1, required_for_next=True),
                    ActionConfig(event="signup completed", probability=0.25, required_for_next=True),
                ],
            ),
            "test": VariantConfig(
                weight=0.5,
                actions=[
                    ActionConfig(event="signup started", probability=1, required_for_next=True),
                    ActionConfig(event="signup completed", probability=0.35, required_for_next=True),
                ],
            ),
        },
    )


def get_default_trend_experiment_config() -> ExperimentConfig:
    return ExperimentConfig(
        number_of_users=2000,
        start_timestamp=datetime.now() - timedelta(days=7),
        end_timestamp=datetime.now(),
        variants={
            "control": VariantConfig(
                weight=0.5,
                actions=[ActionConfig(event="$pageview", count=5, probability=0.25)],
            ),
            "test": VariantConfig(
                weight=0.5,
                actions=[ActionConfig(event="$pageview", count=5, probability=0.35)],
            ),
        },
    )


def get_default_config(type) -> ExperimentConfig:
    match type:
        case "funnel":
            return get_default_funnel_experiment_config()
        case "trend":
            return get_default_trend_experiment_config()
        case _:
            raise ValueError(f"Invalid experiment type: {type}")


class Command(BaseCommand):
    help = "Generate experiment test data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            type=str,
            choices=["trend", "funnel"],
            default="trend",
            help="Type of experiment data to generate or configuration to initialize.",
        )

        parser.add_argument(
            "--init-config",
            type=str,
            help="Initialize a new experiment configuration file at the specified path. Does not generate data.",
        )
        parser.add_argument("--experiment-id", type=str, help="Experiment ID (feature flag name)")
        parser.add_argument("--config", type=str, help="Path to experiment config file")

    def handle(self, *args, **options):
        # Make sure this runs in development environment only
        if not settings.DEBUG:
            raise ValueError("This command should only be run in development! DEBUG must be True.")

        experiment_type = options.get("type")

        if init_config_path := options.get("init_config"):
            with open(init_config_path, "w") as f:
                f.write(get_default_config(experiment_type).model_dump_json(indent=2))
            logging.info(f"Created example {experiment_type} configuration file at: {init_config_path}")
            return

        experiment_id = options.get("experiment_id")
        config_path = options.get("config")

        # Validate required arguments
        if not experiment_id:
            raise ValueError("--experiment-id is missing!")

        if config_path is None and experiment_type is None:
            raise ValueError("--config <path-to-file> or --type trends|funnel is missing!")

        if config_path:
            with open(config_path) as config_file:
                config_data = json.load(config_file)

            try:
                # Use the ExperimentConfig model to parse and validate the JSON data
                experiment_config = ExperimentConfig(**config_data)
            except ValidationError as e:
                raise ValueError(f"Invalid configuration: {e}")
        else:
            experiment_config = get_default_config(experiment_type)

        variants = list(experiment_config.variants.keys())
        variant_counts = {variant: 0 for variant in variants}

        for _ in range(experiment_config.number_of_users):
            variant = random.choices(
                variants,
                weights=[v.weight for v in experiment_config.variants.values()],
            )[0]
            variant_counts[variant] += 1
            distinct_id = str(uuid.uuid4())
            random_timestamp = datetime.fromtimestamp(
                random.uniform(
                    experiment_config.start_timestamp.timestamp(),
                    experiment_config.end_timestamp.timestamp() - 3600,
                )
            )

            posthoganalytics.capture(
                distinct_id=distinct_id,
                event="$feature_flag_called",
                timestamp=random_timestamp,
                properties={
                    "$feature_flag_response": variant,
                    "$feature_flag": experiment_id,
                },
            )

            should_stop = False
            for action in experiment_config.variants[variant].actions:
                for _ in range(action.count):
                    if random.random() < action.probability:
                        posthoganalytics.capture(
                            distinct_id=distinct_id,
                            event=action.event,
                            timestamp=random_timestamp + timedelta(minutes=1),
                            properties={
                                f"$feature/{experiment_id}": variant,
                            },
                        )
                    else:
                        if action.required_for_next:
                            should_stop = True
                            break
                if should_stop:
                    break

        # TODO: need to figure out how to wait for the data to be flushed. shutdown() doesn't work as expected.
        time.sleep(2)
        posthoganalytics.shutdown()

        logging.info(f"Generated data for {experiment_id}")
        logging.info(f"Variant counts: {variant_counts}")
