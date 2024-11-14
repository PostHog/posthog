import asyncio
import json
from os import makedirs, path

import structlog
from django.core.management.base import BaseCommand

from ee.hogai.eval.utils import EVAL_DATASETS, build_and_evaluate_graph, load_test_cases
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Generate datasets to evaluate the correctness of the assistant."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, help="Team ID to generate the dataset for", default=1)
        parser.add_argument("--batch-size", type=int, help="Batch size", default=10)
        parser.add_argument(
            "--nodes",
            nargs="*",
            type=str,
            help="Nodes to generate the datasets for",
            default=list(EVAL_DATASETS.keys()),
            choices=list(EVAL_DATASETS.keys()),
        )

    async def import_data_async(self, options):
        team = await Team.objects.aget(pk=options["team_id"])

        output_path = path.join("ee", "hogai", "eval", "compiled_datasets")
        if not path.exists(output_path):
            makedirs(output_path, exist_ok=True)

        for node in options["nodes"]:
            test_cases = load_test_cases(node, load_compiled=False)

            dataset: list[dict] = []
            for i in range(0, len(test_cases), options["batch_size"]):
                batch = test_cases[i : i + options["batch_size"]]
                res = await asyncio.gather(*[build_and_evaluate_graph(node, team, data) for data in batch])
                for data, actual_output in zip(batch, res):
                    for i, message in enumerate(data.messages):
                        message.actual_output = actual_output[i]
                    dataset.append(data.model_dump())
            with open(path.join(output_path, EVAL_DATASETS[node]), "w") as f:
                json.dump(dataset, f, indent=4)

    def handle(self, *args, **options):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.import_data_async(options))
        logger.info("The evaluation dataset has been generated.")
