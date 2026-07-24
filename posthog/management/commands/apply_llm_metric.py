from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import User

from products.experiments.backend.llm_metric_templates import TEMPLATE_NAMES, apply_metric_to_experiment
from products.experiments.backend.models.experiment import Experiment


class Command(BaseCommand):
    help = "Apply an LLM metric template to an existing experiment (dev-only)."

    def add_arguments(self, parser):
        parser.add_argument("--experiment-id", type=int, required=True, help="Experiment row id")
        parser.add_argument(
            "--template",
            type=str,
            choices=TEMPLATE_NAMES,
            default="cost",
            help=f"Template name. One of: {', '.join(TEMPLATE_NAMES)}",
        )
        parser.add_argument(
            "--prompt-name",
            type=str,
            required=True,
            help="Value to use in the $ai_prompt_name filter",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace all existing primary metrics instead of appending",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command should only be run in development! DEBUG must be True.")

        try:
            experiment = Experiment.objects.get(id=options["experiment_id"])
        except Experiment.DoesNotExist:
            raise CommandError(f"Experiment id={options['experiment_id']} not found")

        user = User.objects.filter(last_login__isnull=False).order_by("-last_login").first()
        if user is None:
            user = User.objects.first()
        if user is None:
            raise CommandError("No User found to attribute the change to. Create one and try again.")

        experiment = apply_metric_to_experiment(
            experiment,
            options["template"],
            options["prompt_name"],
            user=user,
            replace=options["replace"],
        )

        self.stdout.write(
            f"Applied template '{options['template']}' (prompt_name='{options['prompt_name']}') "
            f"to experiment id={experiment.id}. "
            f"Metric count after apply: {len(experiment.metrics or [])}"
        )
