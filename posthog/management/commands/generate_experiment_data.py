import sys
import json
import time
import uuid
import random
import logging
from datetime import datetime, timedelta
from typing import Any, Literal, Union

from django.conf import settings
from django.core.management.base import BaseCommand

import posthoganalytics
from pydantic import BaseModel, Field, ValidationError

from posthog.models import Team, User
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary


def initialize_self_capture():
    """Initialize self-capture for posthoganalytics in management command context"""
    try:
        user = (
            User.objects.filter(last_login__isnull=False).order_by("-last_login").select_related("current_team").first()
        )
        team = None
        if user and getattr(user, "current_team", None):
            team = user.current_team
        else:
            team = Team.objects.only("api_token").first()

        if team:
            posthoganalytics.disabled = False
            posthoganalytics.api_key = team.api_token
            posthoganalytics.host = settings.SITE_URL
            logging.info(f"Self-capture initialized with team {team.name} (API key: {team.api_token[:10]}...)")
            return team
        else:
            logging.warning("No team found for self-capture initialization. Aborting")
            sys.exit(1)
    except Exception as e:
        logging.warning(f"Failed to initialize self-capture: {e}")
        sys.exit(1)


class NormalDistributionParams(BaseModel):
    mean: float
    stddev: float


class Distribution(BaseModel):
    distribution: Literal["normal"]
    params: NormalDistributionParams


class ActionConfig(BaseModel):
    event: str
    probability: float
    count: int = 1
    required_for_next: bool = False
    properties: dict[str, Union[Distribution, object]] = Field(default_factory=dict)

    def model_post_init(self, __context) -> None:
        if self.required_for_next and self.count > 1:
            raise ValueError("'required_for_next' cannot be used with 'count' greater than 1")

        # Convert any raw distribution dictionaries to Distribution objects
        for key, value in self.properties.items():
            if isinstance(value, dict) and "distribution" in value:
                self.properties[key] = Distribution(**value)


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


def get_default_revenue_experiment_config() -> ExperimentConfig:
    return ExperimentConfig(
        number_of_users=2000,
        start_timestamp=datetime.now() - timedelta(days=7),
        end_timestamp=datetime.now(),
        variants={
            "control": VariantConfig(
                weight=0.5,
                actions=[
                    ActionConfig(
                        event="checkout completed",
                        count=5,
                        probability=0.25,
                        properties={
                            "revenue": Distribution(
                                distribution="normal", params=NormalDistributionParams(mean=100, stddev=10)
                            )
                        },
                    )
                ],
            ),
            "test": VariantConfig(
                weight=0.5,
                actions=[
                    ActionConfig(
                        event="checkout completed",
                        count=5,
                        probability=0.35,
                        properties={
                            "revenue": Distribution(
                                distribution="normal", params=NormalDistributionParams(mean=105, stddev=10)
                            )
                        },
                    )
                ],
            ),
        },
    )


def get_default_config(type) -> ExperimentConfig:
    match type:
        case "funnel":
            return get_default_funnel_experiment_config()
        case "trend":
            return get_default_trend_experiment_config()
        case "revenue":
            return get_default_revenue_experiment_config()
        case _:
            raise ValueError(f"Invalid experiment type: {type}")


class Command(BaseCommand):
    help = "Generate experiment test data"

    # Lists for generating realistic person properties
    FIRST_NAMES = [
        "John",
        "Jane",
        "Michael",
        "Sarah",
        "David",
        "Emma",
        "Alex",
        "Lisa",
        "Chris",
        "Anna",
        "James",
        "Mary",
        "Robert",
        "Patricia",
        "William",
        "Jennifer",
        "Daniel",
        "Linda",
        "Joseph",
        "Barbara",
        "Thomas",
        "Elizabeth",
        "Charles",
        "Susan",
        "Christopher",
        "Jessica",
        "Matthew",
        "Karen",
        "Anthony",
        "Nancy",
        "Mark",
        "Betty",
        "Donald",
        "Dorothy",
        "Paul",
        "Sandra",
        "Steven",
        "Ashley",
        "Kenneth",
        "Kimberly",
        "Kevin",
        "Donna",
        "Brian",
        "Michelle",
        "George",
        "Carol",
        "Edward",
        "Amanda",
        "Ronald",
        "Melissa",
    ]

    LAST_NAMES = [
        "Smith",
        "Johnson",
        "Williams",
        "Brown",
        "Jones",
        "Garcia",
        "Miller",
        "Davis",
        "Rodriguez",
        "Martinez",
        "Anderson",
        "Taylor",
        "Thomas",
        "Jackson",
        "White",
        "Harris",
        "Martin",
        "Thompson",
        "Moore",
        "Young",
        "Allen",
        "King",
        "Wright",
        "Scott",
        "Green",
        "Baker",
        "Hill",
        "Adams",
        "Nelson",
        "Campbell",
        "Mitchell",
        "Roberts",
        "Carter",
        "Phillips",
        "Evans",
        "Turner",
        "Torres",
        "Parker",
        "Collins",
        "Edwards",
        "Stewart",
        "Flores",
        "Morris",
        "Nguyen",
        "Murphy",
        "Rivera",
        "Cook",
        "Rogers",
        "Morgan",
        "Peterson",
    ]

    COMPANIES = [
        "Acme Corp",
        "TechStart Inc",
        "Global Solutions",
        "Innovation Labs",
        "Digital Dynamics",
        "Future Systems",
        "Creative Agency",
        "DataWorks",
        "CloudTech",
        "Smart Solutions",
        "NextGen Industries",
        "Elite Consulting",
        "Peak Performance",
        "Visionary Ventures",
        "Strategic Partners",
        "Dynamic Solutions",
        "Progressive Systems",
        "Advanced Analytics",
        "Quantum Computing",
        "AI Innovations",
        "Blockchain Solutions",
        "Cyber Security Inc",
        "Green Energy Co",
        "BioTech Labs",
        "Space Technologies",
        "Robotics International",
        "Virtual Reality Studios",
        "Augmented Systems",
        "Machine Learning Corp",
        "Data Science Hub",
    ]

    CITIES = [
        "New York",
        "London",
        "San Francisco",
        "Berlin",
        "Tokyo",
        "Sydney",
        "Toronto",
        "Paris",
        "Chicago",
        "Los Angeles",
        "Boston",
        "Seattle",
        "Austin",
        "Denver",
        "Miami",
        "Portland",
        "Amsterdam",
        "Singapore",
        "Hong Kong",
        "Dubai",
        "Stockholm",
        "Copenhagen",
        "Munich",
        "Zurich",
        "Barcelona",
        "Madrid",
        "Rome",
        "Milan",
        "Vienna",
        "Prague",
        "Warsaw",
        "Budapest",
    ]

    COUNTRIES = [
        "US",
        "UK",
        "CA",
        "AU",
        "DE",
        "FR",
        "JP",
        "IN",
        "NL",
        "SG",
        "HK",
        "AE",
        "SE",
        "DK",
        "CH",
        "ES",
        "IT",
        "AT",
        "CZ",
        "PL",
        "HU",
        "KR",
        "BR",
        "MX",
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            type=str,
            choices=["trend", "funnel", "revenue"],
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
        parser.add_argument(
            "--generate-session-replays",
            action="store_true",
            help="Generate session replay data for a subset of sessions",
        )
        parser.add_argument(
            "--replay-probability",
            type=float,
            default=0.3,
            help="Probability (0.0 to 1.0) that a session will have replay data (default: 0.3)",
        )
        parser.add_argument(
            "--create-person-profiles",
            action="store_true",
            help="Create person profiles with properties for generated users",
        )
        parser.add_argument(
            "--person-properties-ratio",
            type=float,
            default=0.7,
            help="Ratio of users to get detailed person properties (0.0 to 1.0, default: 0.7)",
        )

    def handle(self, *args, **options):
        # Make sure this runs in development environment only
        if not settings.DEBUG:
            raise ValueError("This command should only be run in development! DEBUG must be True.")

        team = initialize_self_capture()

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

        generate_replays = options.get("generate_session_replays", False)
        replay_probability = options.get("replay_probability", 0.3)
        replay_count = 0

        create_person_profiles = options.get("create_person_profiles", False)
        person_properties_ratio = options.get("person_properties_ratio", 0.7)
        persons_created = 0

        for _ in range(experiment_config.number_of_users):
            variant = random.choices(
                variants,
                weights=[v.weight for v in experiment_config.variants.values()],
            )[0]
            variant_counts[variant] += 1
            distinct_id = str(uuid.uuid4())
            session_id = str(uuid.uuid4())
            feature_flag_property = f"$feature/{experiment_id}"
            random_timestamp = datetime.fromtimestamp(
                random.uniform(
                    experiment_config.start_timestamp.timestamp(),
                    experiment_config.end_timestamp.timestamp() - 3600,
                )
            )

            # Create person profile if enabled
            if create_person_profiles:
                is_identified = random.random() < person_properties_ratio
                person_properties = self._generate_person_properties(is_identified)

                # Send $identify event to create/update person profile
                # In backend SDKs, we need to send an event with $set properties
                posthoganalytics.capture(
                    distinct_id=distinct_id,
                    event="$identify",
                    timestamp=random_timestamp,
                    properties={
                        "$set": person_properties,
                    },
                )
                persons_created += 1

            posthoganalytics.capture(
                distinct_id=distinct_id,
                event="$feature_flag_called",
                timestamp=random_timestamp,
                properties={
                    feature_flag_property: variant,
                    "$feature_flag_response": variant,
                    "$feature_flag": experiment_id,
                    "$session_id": session_id,
                },
            )

            should_stop = False
            time_increment = 1
            for action in experiment_config.variants[variant].actions:
                for _ in range(action.count):
                    if random.random() < action.probability:
                        # Prepare properties dictionary
                        properties: dict[str, Any] = {
                            f"$feature/{experiment_id}": variant,
                            "$session_id": session_id,
                        }

                        # Add custom properties, sampling from distributions if needed
                        for prop_name, prop_value in action.properties.items():
                            if isinstance(prop_value, Distribution):
                                # Sample from normal distribution
                                if prop_value.distribution == "normal":
                                    properties[prop_name] = random.gauss(
                                        prop_value.params.mean, prop_value.params.stddev
                                    )
                            else:
                                properties[prop_name] = prop_value

                        posthoganalytics.capture(
                            distinct_id=distinct_id,
                            event=action.event,
                            timestamp=random_timestamp + timedelta(minutes=time_increment),
                            properties=properties,
                        )
                        time_increment += 1
                    else:
                        if action.required_for_next:
                            should_stop = True
                            break
                if should_stop:
                    break

            # Generate session replay data for this session if enabled
            if generate_replays and random.random() < replay_probability:
                replay_count += 1
                # Generate session replay with some activity
                produce_replay_summary(
                    team_id=team.pk,
                    session_id=session_id,
                    distinct_id=distinct_id,
                    first_timestamp=random_timestamp,
                    last_timestamp=random_timestamp + timedelta(minutes=random.randint(5, 30)),
                    first_url=f"https://example.com/experiment/{experiment_id}/{variant}",
                    click_count=random.randint(5, 50),
                    keypress_count=random.randint(10, 100),
                    mouse_activity_count=random.randint(20, 200),
                    active_milliseconds=random.randint(30000, 300000),  # 30s to 5min active time
                    console_log_count=random.randint(0, 10),
                    console_warn_count=random.randint(0, 3),
                    console_error_count=random.randint(0, 2),
                    ensure_analytics_event_in_session=False,  # We already have events from above
                    retention_period_days=90,
                )

        # TODO: need to figure out how to wait for the data to be flushed. shutdown() doesn't work as expected.
        time.sleep(3)
        posthoganalytics.shutdown()

        logging.info(f"Generated data for {experiment_id}")
        logging.info(f"Variant counts: {variant_counts}")
        if generate_replays:
            logging.info(
                f"Generated {replay_count} session replays ({replay_count/experiment_config.number_of_users:.1%} of sessions)"
            )
        if create_person_profiles:
            logging.info(
                f"Created {persons_created} person profiles ({persons_created/experiment_config.number_of_users:.1%} of users)"
            )

    def _generate_person_properties(self, is_identified: bool) -> dict[str, Any]:
        """Generate realistic person properties based on identification status"""
        if is_identified:
            first_name = random.choice(self.FIRST_NAMES)
            last_name = random.choice(self.LAST_NAMES)
            email = self._generate_email(first_name, last_name)

            # Generate comprehensive properties for identified users
            properties = {
                "email": email,
                "name": f"{first_name} {last_name}",
                "first_name": first_name,
                "last_name": last_name,
                "username": self._generate_username(first_name, last_name),
                "company": random.choice(self.COMPANIES),
                "plan": random.choice(["free", "starter", "pro", "enterprise"]),
                "country": random.choice(self.COUNTRIES),
                "city": random.choice(self.CITIES),
                "utm_source": random.choice(["google", "twitter", "linkedin", "direct", "github", "facebook"]),
                "utm_medium": random.choice(["cpc", "social", "email", "organic", "referral"]),
                "utm_campaign": random.choice(["summer2024", "product_launch", "black_friday", "q4_promo", None]),
                "signup_date": self._generate_date_string(365),  # Within last year
                "last_login": self._generate_date_string(30),  # Within last month
                "total_events": random.randint(10, 5000),
                "sessions_count": random.randint(1, 100),
                "is_experiment_demo": True,
                "user_segment": random.choice(["power_user", "regular", "occasional", "new"]),
                "industry": random.choice(["tech", "finance", "healthcare", "retail", "education", "other"]),
                "team_size": random.choice(["1-10", "11-50", "51-200", "201-500", "500+"]),
            }
        else:
            # Generate minimal properties for anonymous users
            properties = {
                "utm_source": random.choice(["google", "twitter", "linkedin", "direct", "github", None]),
                "utm_medium": random.choice(["cpc", "social", "email", "organic", None]),
                "utm_campaign": random.choice(["summer2024", "product_launch", "black_friday", None]),
                "browser": random.choice(["Chrome", "Firefox", "Safari", "Edge"]),
                "os": random.choice(["Windows", "Mac OS X", "Linux", "iOS", "Android"]),
                "is_experiment_demo": True,
            }

        return properties

    def _generate_email(self, first_name: str, last_name: str) -> str:
        """Generate a realistic email address"""
        domains = [
            "gmail.com",
            "yahoo.com",
            "hotmail.com",
            "outlook.com",
            "icloud.com",
            "company.com",
            "startup.io",
            "example.com",
            "test.com",
            "demo.com",
        ]

        first = first_name.lower()
        last = last_name.lower()
        domain = random.choice(domains)

        # Add variety in email formats
        format_choice = random.random()
        if format_choice < 0.3:
            email = f"{first}.{last}@{domain}"
        elif format_choice < 0.5:
            email = f"{first}{random.randint(1, 999)}@{domain}"
        elif format_choice < 0.7:
            email = f"{first}_{last}@{domain}"
        elif format_choice < 0.85:
            email = f"{first[0]}{last}@{domain}"
        else:
            email = f"{first}{last[0]}{random.randint(1, 99)}@{domain}"

        return email

    def _generate_username(self, first_name: str, last_name: str) -> str:
        """Generate a realistic username"""
        first = first_name.lower()
        last = last_name.lower()

        format_choice = random.random()
        if format_choice < 0.2:
            username = f"{first}.{last}"
        elif format_choice < 0.4:
            username = f"{first}{random.randint(1, 999)}"
        elif format_choice < 0.6:
            username = f"{first}_{last}"
        elif format_choice < 0.8:
            username = f"{first}{last[0]}"
        else:
            username = f"{last}.{first}{random.randint(1, 99)}"

        return username

    def _generate_date_string(self, max_days_ago: int) -> str:
        """Generate a date string within the specified number of days ago"""
        days_ago = random.randint(1, max_days_ago)
        date = datetime.now() - timedelta(days=days_ago)
        return date.strftime("%Y-%m-%d")
