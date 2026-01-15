"""
Django management command to sync PostHog entities to/from a local file system.

This creates a human/AI-readable representation of insights, dashboards, cohorts,
actions, experiments, and feature flags in YAML format.

Usage:
    python manage.py sync_entities --team-id 1 export
    python manage.py sync_entities --team-id 1 export --entity-type insights
"""

import re
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

import yaml

from posthog.models import Action, Cohort, Dashboard, DashboardTile, Experiment, FeatureFlag, Insight, Team


def slugify(text: str, max_length: int = 50) -> str:
    """Convert text to a URL-friendly slug."""
    if not text:
        return "untitled"
    # Convert to lowercase and replace spaces with dashes
    slug = text.lower().strip()
    # Replace any non-alphanumeric characters (except dashes) with dashes
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    # Collapse multiple dashes
    slug = re.sub(r"-+", "-", slug)
    # Strip leading/trailing dashes
    slug = slug.strip("-")
    # Truncate to max_length
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "untitled"


def compute_checksum(data: dict) -> str:
    """Compute SHA256 checksum of data (excluding _meta)."""
    data_copy = {k: v for k, v in data.items() if k != "_meta"}
    json_str = json.dumps(data_copy, sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(json_str.encode()).hexdigest()[:16]}"


def serialize_datetime(dt: datetime | None) -> str | None:
    """Serialize datetime to ISO format."""
    if dt is None:
        return None
    return dt.isoformat()


def serialize_user(user) -> dict | None:
    """Serialize a user to basic info."""
    if user is None:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
    }


class EntitySerializer:
    """Base class for entity serialization."""

    entity_type: str = ""
    folder_name: str = ""

    def get_filename(self, entity) -> str:
        raise NotImplementedError

    def serialize(self, entity) -> dict:
        raise NotImplementedError

    def get_refs(self, entity) -> dict:
        return {}


class InsightSerializer(EntitySerializer):
    entity_type = "insight"
    folder_name = "insights"

    def get_filename(self, entity: Insight) -> str:
        slug = slugify(entity.name) if entity.name else "untitled"
        return f"{entity.short_id}-{slug}.yaml"

    def serialize(self, entity: Insight) -> dict:
        data = {
            "name": entity.name or "",
            "description": entity.description or "",
            "saved": entity.saved,
            "favorited": entity.favorited,
        }

        # Include query if present (new-style insights)
        if entity.query:
            data["query"] = entity.query

        # Include filters if present (legacy insights)
        if entity.filters and not entity.query:
            data["filters"] = entity.filters

        return data

    def get_refs(self, entity: Insight) -> dict:
        refs = {}
        # Get dashboards this insight is on
        dashboard_ids = list(
            DashboardTile.objects.filter(insight=entity)
            .exclude(dashboard__deleted=True)
            .values_list("dashboard_id", flat=True)
        )
        if dashboard_ids:
            refs["dashboards"] = dashboard_ids
        return refs

    def get_meta(self, entity: Insight) -> dict:
        return {
            "type": self.entity_type,
            "id": entity.short_id,
            "db_id": entity.id,
            "created_at": serialize_datetime(entity.created_at),
            "created_by": serialize_user(entity.created_by),
            "last_modified_at": serialize_datetime(entity.last_modified_at),
            "last_modified_by": serialize_user(entity.last_modified_by),
        }


class DashboardSerializer(EntitySerializer):
    entity_type = "dashboard"
    folder_name = "dashboards"

    def get_filename(self, entity: Dashboard) -> str:
        slug = slugify(entity.name) if entity.name else "untitled"
        return f"{entity.id}-{slug}.yaml"

    def serialize(self, entity: Dashboard) -> dict:
        data = {
            "name": entity.name or "",
            "description": entity.description or "",
            "pinned": entity.pinned,
        }

        if entity.filters:
            data["filters"] = entity.filters

        # Serialize tiles
        tiles = []
        for tile in DashboardTile.objects.filter(dashboard=entity).select_related("insight", "text"):
            tile_data: dict[str, Any] = {}
            if tile.insight:
                tile_data["insight_ref"] = tile.insight.short_id
            elif tile.text:
                tile_data["type"] = "text"
                tile_data["body"] = tile.text.body

            if tile.layouts:
                tile_data["layouts"] = tile.layouts
            if tile.color:
                tile_data["color"] = tile.color

            tiles.append(tile_data)

        if tiles:
            data["tiles"] = tiles

        return data

    def get_refs(self, entity: Dashboard) -> dict:
        refs = {}
        insight_ids = list(
            DashboardTile.objects.filter(dashboard=entity, insight__isnull=False)
            .exclude(insight__deleted=True)
            .values_list("insight__short_id", flat=True)
        )
        if insight_ids:
            refs["insights"] = insight_ids
        return refs

    def get_meta(self, entity: Dashboard) -> dict:
        return {
            "type": self.entity_type,
            "id": entity.id,
            "created_at": serialize_datetime(entity.created_at),
            "created_by": serialize_user(entity.created_by),
        }


class CohortSerializer(EntitySerializer):
    entity_type = "cohort"
    folder_name = "cohorts"

    def get_filename(self, entity: Cohort) -> str:
        slug = slugify(entity.name) if entity.name else "untitled"
        return f"{entity.id}-{slug}.yaml"

    def serialize(self, entity: Cohort) -> dict:
        data = {
            "name": entity.name or "",
            "description": entity.description or "",
            "is_static": entity.is_static,
        }

        if entity.filters:
            data["filters"] = entity.filters

        if entity.query:
            data["query"] = entity.query

        # Include deprecated groups if present and no filters
        if entity.groups and not entity.filters:
            data["groups"] = entity.groups

        return data

    def get_refs(self, entity: Cohort) -> dict:
        return {}

    def get_meta(self, entity: Cohort) -> dict:
        return {
            "type": self.entity_type,
            "id": entity.id,
            "created_at": serialize_datetime(entity.created_at),
            "created_by": serialize_user(entity.created_by),
            "count": entity.count,
            "last_calculation": serialize_datetime(entity.last_calculation),
        }


class ActionSerializer(EntitySerializer):
    entity_type = "action"
    folder_name = "actions"

    def get_filename(self, entity: Action) -> str:
        slug = slugify(entity.name) if entity.name else "untitled"
        return f"{entity.id}-{slug}.yaml"

    def serialize(self, entity: Action) -> dict:
        data = {
            "name": entity.name or "",
            "description": entity.description or "",
        }

        if entity.steps_json:
            data["steps"] = entity.steps_json

        if entity.post_to_slack:
            data["post_to_slack"] = entity.post_to_slack
            if entity.slack_message_format:
                data["slack_message_format"] = entity.slack_message_format

        return data

    def get_refs(self, entity: Action) -> dict:
        return {}

    def get_meta(self, entity: Action) -> dict:
        return {
            "type": self.entity_type,
            "id": entity.id,
            "created_at": serialize_datetime(entity.created_at),
            "created_by": serialize_user(entity.created_by),
            "updated_at": serialize_datetime(entity.updated_at),
        }


class ExperimentSerializer(EntitySerializer):
    entity_type = "experiment"
    folder_name = "experiments"

    def get_filename(self, entity: Experiment) -> str:
        slug = slugify(entity.name) if entity.name else "untitled"
        return f"{entity.id}-{slug}.yaml"

    def serialize(self, entity: Experiment) -> dict:
        data = {
            "name": entity.name or "",
            "description": entity.description or "",
            "type": entity.type,
            "archived": entity.archived,
        }

        if entity.start_date:
            data["start_date"] = serialize_datetime(entity.start_date)
        if entity.end_date:
            data["end_date"] = serialize_datetime(entity.end_date)

        if entity.filters:
            data["filters"] = entity.filters

        if entity.parameters:
            data["parameters"] = entity.parameters

        if entity.variants:
            data["variants"] = entity.variants

        if entity.metrics:
            data["metrics"] = entity.metrics

        if entity.metrics_secondary:
            data["metrics_secondary"] = entity.metrics_secondary

        if entity.stats_config:
            data["stats_config"] = entity.stats_config

        if entity.conclusion:
            data["conclusion"] = entity.conclusion
            if entity.conclusion_comment:
                data["conclusion_comment"] = entity.conclusion_comment

        return data

    def get_refs(self, entity: Experiment) -> dict:
        refs = {}
        if entity.feature_flag_id:
            refs["feature_flag"] = entity.feature_flag_id
            # Also include the key for easier reference
            if entity.feature_flag:
                refs["feature_flag_key"] = entity.feature_flag.key
        if entity.exposure_cohort_id:
            refs["exposure_cohort"] = entity.exposure_cohort_id
        return refs

    def get_meta(self, entity: Experiment) -> dict:
        return {
            "type": self.entity_type,
            "id": entity.id,
            "created_at": serialize_datetime(entity.created_at),
            "created_by": serialize_user(entity.created_by),
            "updated_at": serialize_datetime(entity.updated_at),
        }


class FeatureFlagSerializer(EntitySerializer):
    entity_type = "feature_flag"
    folder_name = "feature_flags"

    def get_filename(self, entity: FeatureFlag) -> str:
        # Feature flags use id-key as filename, sanitized for filesystem safety
        safe_key = slugify(entity.key, max_length=80)
        return f"{entity.id}-{safe_key}.yaml"

    def serialize(self, entity: FeatureFlag) -> dict:
        data = {
            "key": entity.key,
            "name": entity.name or "",  # This is actually the description field
            "active": entity.active,
            "ensure_experience_continuity": entity.ensure_experience_continuity,
        }

        if entity.filters:
            data["filters"] = entity.filters

        if entity.rollout_percentage is not None:
            data["rollout_percentage"] = entity.rollout_percentage

        if entity.rollback_conditions:
            data["rollback_conditions"] = entity.rollback_conditions

        return data

    def get_refs(self, entity: FeatureFlag) -> dict:
        refs = {}

        # Check if this flag is used by an experiment
        experiments = Experiment.objects.filter(feature_flag=entity, deleted=False)
        experiment_ids = list(experiments.values_list("id", flat=True))
        if experiment_ids:
            refs["experiments"] = experiment_ids

        # Extract cohort references from filters
        cohort_ids = self._extract_cohort_ids(entity.filters)
        if cohort_ids:
            refs["cohorts"] = list(cohort_ids)

        return refs

    def _extract_cohort_ids(self, filters: dict | None) -> set[int]:
        """Extract cohort IDs from feature flag filters."""
        cohort_ids: set[int] = set()
        if not filters:
            return cohort_ids

        groups = filters.get("groups", [])
        for group in groups:
            properties = group.get("properties", [])
            for prop in properties:
                if prop.get("type") == "cohort":
                    value = prop.get("value")
                    if isinstance(value, int):
                        cohort_ids.add(value)
                    elif isinstance(value, str) and value.isdigit():
                        cohort_ids.add(int(value))

        return cohort_ids

    def get_meta(self, entity: FeatureFlag) -> dict:
        return {
            "type": self.entity_type,
            "id": entity.id,
            "version": entity.version,
            "created_at": serialize_datetime(entity.created_at),
            "created_by": serialize_user(entity.created_by),
            "updated_at": serialize_datetime(entity.updated_at),
            "last_modified_by": serialize_user(entity.last_modified_by),
        }


ENTITY_SERIALIZERS: dict[str, type[EntitySerializer]] = {
    "insights": InsightSerializer,
    "dashboards": DashboardSerializer,
    "cohorts": CohortSerializer,
    "actions": ActionSerializer,
    "experiments": ExperimentSerializer,
    "feature_flags": FeatureFlagSerializer,
}


class Command(BaseCommand):
    help = "Sync PostHog entities to/from local YAML files for AI agent access"

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=["export"],
            help="Action to perform: export (DB to files)",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID to sync entities for",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=".posthog",
            help="Output directory for entity files (default: .posthog)",
        )
        parser.add_argument(
            "--entity-type",
            type=str,
            choices=list(ENTITY_SERIALIZERS.keys()),
            help="Only sync a specific entity type",
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        output_dir = Path(options["output_dir"])
        action = options["action"]
        entity_type = options.get("entity_type")

        # Validate team exists
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team with ID {team_id} does not exist")

        self.stdout.write(f"Syncing entities for team: {team.name} (ID: {team_id})")

        if action == "export":
            self.export_entities(team, output_dir, entity_type)

    def export_entities(self, team: Team, output_dir: Path, entity_type: str | None):
        """Export entities from database to YAML files."""
        # Create directory structure directly in output_dir (no team subfolder)
        self._create_directories(output_dir)

        # Track all entities for index generation
        all_entities: list[dict] = []
        references: dict[str, dict] = {}

        # Determine which entity types to export
        entity_types = [entity_type] if entity_type else list(ENTITY_SERIALIZERS.keys())

        for etype in entity_types:
            serializer_class = ENTITY_SERIALIZERS[etype]
            serializer = serializer_class()
            entities = self._get_entities(team, etype)

            self.stdout.write(f"  Exporting {len(entities)} {etype}...")

            entity_dir = output_dir / serializer.folder_name
            entity_dir.mkdir(parents=True, exist_ok=True)

            for entity in entities:
                # Serialize entity
                data = serializer.serialize(entity)
                refs = serializer.get_refs(entity)
                meta = serializer.get_meta(entity)

                # Compute checksum before adding meta
                checksum = compute_checksum(data)

                # Build full document
                full_data = {
                    "_meta": {
                        **meta,
                        "checksum": checksum,
                        "last_synced": timezone.now().isoformat(),
                    },
                    **data,
                }

                if refs:
                    full_data["_refs"] = refs

                # Write YAML file
                filename = serializer.get_filename(entity)
                filepath = entity_dir / filename
                self._write_yaml(filepath, full_data, team.id)

                # Track for index
                entity_id = meta.get("id")
                entity_name = data.get("name") or data.get("key", "")
                all_entities.append(
                    {
                        "type": serializer.entity_type,
                        "id": entity_id,
                        "name": entity_name,
                    }
                )

                # Track references
                if refs:
                    ref_key = f"{serializer.entity_type}:{entity_id}"
                    references[ref_key] = {
                        "references": [
                            {"type": k.rstrip("s"), "id": v}
                            if not isinstance(v, list)
                            else {"type": k.rstrip("s"), "ids": v}
                            for k, v in refs.items()
                        ]
                    }

        # Generate index files
        self._generate_indexes(output_dir, all_entities, references)

        # Write config
        self._write_config(output_dir, team)

        self.stdout.write(self.style.SUCCESS(f"Export complete! Files written to {output_dir}"))

    def _create_directories(self, output_dir: Path):
        """Create the directory structure for entity files."""
        directories = [
            output_dir / "insights",
            output_dir / "dashboards",
            output_dir / "cohorts",
            output_dir / "actions",
            output_dir / "experiments",
            output_dir / "feature_flags",
            output_dir / "_meta",
            output_dir / "_index",
        ]
        for d in directories:
            d.mkdir(parents=True, exist_ok=True)

    def _get_entities(self, team: Team, entity_type: str) -> list:
        """Get all entities of a given type for a team."""
        if entity_type == "insights":
            return list(
                Insight.objects.filter(team=team, deleted=False, saved=True)
                .select_related("created_by", "last_modified_by")
                .order_by("-last_modified_at")
            )
        elif entity_type == "dashboards":
            return list(
                Dashboard.objects.filter(team=team, deleted=False).select_related("created_by").order_by("-created_at")
            )
        elif entity_type == "cohorts":
            return list(
                Cohort.objects.filter(team=team, deleted=False).select_related("created_by").order_by("-created_at")
            )
        elif entity_type == "actions":
            return list(
                Action.objects.filter(team=team, deleted=False).select_related("created_by").order_by("-created_at")
            )
        elif entity_type == "experiments":
            return list(
                Experiment.objects.filter(team=team, deleted=False)
                .select_related("created_by", "feature_flag")
                .order_by("-created_at")
            )
        elif entity_type == "feature_flags":
            return list(
                FeatureFlag.objects.filter(team=team, deleted=False)
                .select_related("created_by", "last_modified_by")
                .order_by("-created_at")
            )
        return []

    def _write_yaml(self, filepath: Path, data: dict, team_id: int):
        """Write data to a YAML file with a header comment."""
        with open(filepath, "w") as f:
            # Write header comment
            entity_type = data.get("_meta", {}).get("type", "entity")
            f.write(f"# PostHog {entity_type.replace('_', ' ').title()} - team-{team_id}\n")

            # Custom representer for None values
            def represent_none(dumper, _):
                return dumper.represent_scalar("tag:yaml.org,2002:null", "~")

            yaml.add_representer(type(None), represent_none)

            # Write YAML with proper formatting
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )

    def _generate_indexes(self, output_dir: Path, entities: list[dict], references: dict):
        """Generate index files for easy searching."""
        index_dir = output_dir / "_index"

        # Generate by_name.txt
        by_name_path = index_dir / "by_name.txt"
        with open(by_name_path, "w") as f:
            for entity in sorted(entities, key=lambda e: (e["type"], str(e["name"]).lower())):
                f.write(f"{entity['type']}:{entity['id']}:{entity['name']}\n")

        # Generate references.json
        references_path = index_dir / "references.json"
        with open(references_path, "w") as f:
            json.dump(references, f, indent=2, default=str)

    def _write_config(self, output_dir: Path, team: Team):
        """Write configuration file."""
        config = {
            "team_id": team.id,
            "team_name": team.name,
            "schema_version": 1,
            "last_export": timezone.now().isoformat(),
        }
        config_path = output_dir / "_meta" / "config.json"
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        # Also write sync_state.json
        sync_state = {
            "last_sync": timezone.now().isoformat(),
            "sync_direction": "export",
        }
        sync_state_path = output_dir / "_meta" / "sync_state.json"
        with open(sync_state_path, "w") as f:
            json.dump(sync_state, f, indent=2)
