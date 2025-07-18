import logging
import os
from structlog import get_logger
from django.core.management.base import BaseCommand

from posthog.temporal.data_imports.sources.common.source_config_generator import SourceConfigGenerator


logger = get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Generate @config.config classes from data warehouse source definitions"

    def handle(self, *args, **options):
        logger.info("Generating source configs from AVAILABLE_SOURCES...")

        generator = SourceConfigGenerator()
        output = generator.generate_all_configs()

        output_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "temporal", "data_imports", "sources", "generated_configs.py"
        )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w") as f:
            f.write(output)

        logger.info(f"Generated source configs written to: {output_path}")
        logger.info(f"Generated {len(generator.generated_classes)} main config classes")
        logger.info(f"Generated {len(generator.nested_configs)} nested config classes")
