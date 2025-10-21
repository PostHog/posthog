import os
import re
from typing import TypedDict

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

import textcase
from git import Repo
from structlog import get_logger

SOURCE_TEMPLATE = """\
from typing import cast

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.sources.common.base import BaseSource, FieldType
from posthog.temporal.data_imports.sources.common.config import Config
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.warehouse.types import ExternalDataSourceType

# TODO({git_user}): implement the source logic for {pascal}Source


@SourceRegistry.register
class {pascal}Source(BaseSource[Config]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.{caps}

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.{constant},
            iconPath="/static/services/{kebab}.png",
            label="{pascal}",  # only needed if the readable name is complex. delete otherwise
            caption=None,  # only needed if you want to inline docs
            docsUrl=None,  # TODO({git_user}): link to the docs in the website, full path including https://
            fields=cast(list[FieldType], []), # TODO({git_user}): add source config fields here
        )

    def validate_credentials(self, config: Config, team_id: int) -> tuple[bool, str | None]:
        # TODO({git_user}): implement the logic to validate the credentials of your source,
        # e.g. check the validity of API keys. returns a tuple of whether the credentials are valid,
        # and if not, returns an error message to return to the user
        raise NotImplementedError()

    def get_schemas(self, config: Config, team_id: int, with_counts: bool = False) -> list[SourceSchema]:
        raise NotImplementedError()

    def source_for_pipeline(self, config: Config, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError()
"""

logger = get_logger(__name__)


class NameTransforms(TypedDict):
    pascal: str
    snake: str
    kebab: str
    constant: str
    caps: str


class Command(BaseCommand):
    help = "Create a new unreleased data warehouse source"

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            type=str,
            help="Name of the external data source (e.g., Stripe, Meta Ads)",
        )

    def handle(self, *args, **options):
        name = options.get("name")
        if not name:
            name = input("What source are you scaffolding? (e.g. Stripe, Meta Ads): ").strip()
        if not name:
            raise CommandError("You entered a non-empty name for this source. Aborting...")

        repo = Repo(".", search_parent_directories=True)

        name_transforms: NameTransforms = {
            "pascal": textcase.pascal(name),
            "snake": textcase.snake(name),
            "kebab": textcase.kebab(name),
            "constant": textcase.constant(name),
            "caps": textcase.constant(name).replace("_", ""),
        }

        self._setup_source_structure(repo, transforms=name_transforms)

        self._add_warehouse_types_enum(repo, transforms=name_transforms)
        self._add_schema_py_enum(repo, transforms=name_transforms)
        self._add_schema_general_ts_list_item(repo, transforms=name_transforms)

        if self._has_pending_migrations(repo):
            self.stdout.write(
                self.style.WARNING(
                    "The max_migration.txt file is modified in the working tree. Skipping makemigrations..."
                )
            )
        else:
            call_command("makemigrations")  # TODO: figure out how to only migrate the relevant tables

    def _split_file_by_regex(self, file: str, regex: str) -> tuple[str, str]:
        """Returns file contents pre and post a regex match (pre is inclusive of the regex match)"""
        assert os.path.exists(file), f"File not found: {file}"

        with open(file) as f:
            content = f.read()
        match = re.search(regex, content, re.MULTILINE)
        assert match, f"File {file} no longer conforms to the expected format for the create_warehouse_source command"

        insert_idx = match.end()
        return content[:insert_idx], content[insert_idx:]

    def _entry_exists_in_contiguous_text_block(self, entry: str, block: str) -> bool:
        for line in block.split("\n"):
            if not line.strip():
                break
            if entry in line.strip():
                return True
        return False

    def _format_file_line(self, line: str, indent_level: int = 1, end: str = "\n"):
        indent_spaces = 4 * indent_level * " "
        line = indent_spaces + line
        if not line.endswith(end):
            line += end
        return line

    def _has_pending_migrations(self, repo: Repo):
        unstaged_changes = [item.a_path for item in repo.index.diff(None)]
        unstaged_changes += [item.b_path for item in repo.index.diff(None)]
        staged_changes = [item.a_path for item in repo.index.diff("HEAD")]
        staged_changes = [item.b_path for item in repo.index.diff("HEAD")]
        migration_file = "max_migration.txt"
        return migration_file in unstaged_changes or migration_file in staged_changes

    def _setup_source_structure(self, repo: Repo, transforms: NameTransforms):
        sources_root = os.path.join(repo.working_dir, "posthog", "temporal", "data_imports", "sources")
        assert os.path.exists(sources_root), f"Sources root {sources_root} not found"

        source_dir = os.path.join(sources_root, transforms["snake"])
        if not os.path.exists(source_dir):
            os.mkdir(source_dir)
            self.stdout.write(self.style.SUCCESS(f"Created directory: {source_dir}"))
        else:
            self.stdout.write(self.style.WARNING(f"Directory exists: {source_dir}"))

        git_user = str(repo.config_reader().get_value("user", "name"))
        starter_template = SOURCE_TEMPLATE.format(git_user=git_user, **transforms)

        source_file = os.path.join(source_dir, "source.py")
        if not os.path.exists(source_file):
            with open(source_file, "w") as f:
                f.write(starter_template)
            self.stdout.write(self.style.SUCCESS(f"Created file: {source_file}"))
        else:
            self.stdout.write(self.style.WARNING(f"File exists: {source_file}"))

    def _add_warehouse_types_enum(self, repo: Repo, transforms: NameTransforms):
        file = os.path.join(repo.working_dir, "posthog", "warehouse", "types.py")
        assert os.path.exists(file), f"File not found {file}"

        key, val = transforms["caps"], transforms["pascal"]
        regex = r"(^class ExternalDataSourceType\(models\.TextChoices\)\:\n)"
        pre, post = self._split_file_by_regex(file, regex)
        if self._entry_exists_in_contiguous_text_block(entry=key, block=post):
            self.stdout.write(self.style.WARNING(f"Source entry already exists in {file}. Skipping..."))
            return

        line = self._format_file_line(f'{key} = "{val}", "{val}"')
        with open(file, "w") as f:
            f.write("".join([pre, line, post]))
        self.stdout.write(self.style.SUCCESS(f"Added source entry to {file}..."))

    def _add_schema_py_enum(self, repo: Repo, transforms: NameTransforms):
        file = os.path.join(repo.working_dir, "posthog", "schema.py")
        assert os.path.exists(file), f"File not found {file}"

        key, val = transforms["constant"], transforms["pascal"]
        regex = r"(^class ExternalDataSourceType\(StrEnum\)\:\n)"
        pre, post = self._split_file_by_regex(file, regex)
        if self._entry_exists_in_contiguous_text_block(entry=key, block=post):
            self.stdout.write(self.style.WARNING(f"Source entry already exists in {file}. Skipping..."))
            return

        line = self._format_file_line(f'{key} = "{val}"')
        with open(file, "w") as f:
            f.write("".join([pre, line, post]))
        self.stdout.write(self.style.SUCCESS(f"Added source entry to {file}..."))

    def _add_schema_general_ts_list_item(self, repo: Repo, transforms: NameTransforms):
        file = os.path.join(repo.working_dir, "frontend", "src", "queries", "schema", "schema-general.ts")
        assert os.path.exists(file), f"File not found {file}"

        val = transforms["pascal"]
        regex = r"(^export const externalDataSources = \[\n)"
        pre, post = self._split_file_by_regex(file, regex)
        if self._entry_exists_in_contiguous_text_block(entry=val, block=post):
            self.stdout.write(self.style.WARNING(f"Source entry already exists in {file}. Skipping..."))
            return

        line = self._format_file_line(f'"{val}",')
        with open(file, "w") as f:
            f.write("".join([pre, line, post]))
        self.stdout.write(self.style.SUCCESS(f"Added source entry to {file}..."))
        pass
