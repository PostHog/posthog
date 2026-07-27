"""Relationship proposal lifecycle -- promote a reviewed join into a real DataWarehouseJoin.

Proposals are deduped undirected (a->b and b->a share a fingerprint), so a rejection blocks the pair
in both orientations forever. Accepting re-validates the join keys and runs a live probe (a blessed
join is a demonstrated-working join) before creating exactly one join under a row lock.
"""

import json
import hashlib
from typing import Optional

from django.db import (
    IntegrityError,
    connection as db_connection,
    transaction,
)
from django.db.models import QuerySet
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.lazy_join_tags import DATA_WAREHOUSE, DATA_WAREHOUSE_EXPERIMENTS
from posthog.hogql.database.models import LazyJoin
from posthog.hogql.database.utils import get_join_field_chain
from posthog.hogql.database.warehouse_join_resolvers import data_warehouse_resolver_params
from posthog.hogql.errors import (
    ExposedHogQLError,
    SyntaxError as HogQLSyntaxError,
)
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.data_tools.backend.facade.models import DataWarehouseJoin

from ..facade.enums import RelationshipStatus
from ..models import RelationshipProposal
from .exceptions import CatalogConflict


def _fingerprint(source_name: str, source_key: str, joining_name: str, joining_key: str) -> str:
    endpoints = sorted(
        [
            [source_name, _canonicalize_join_key(source_key)],
            [joining_name, _canonicalize_join_key(joining_key)],
        ]
    )
    return hashlib.sha256(json.dumps(endpoints, sort_keys=True).encode()).hexdigest()


def _canonicalize_join_key(key: str) -> str:
    try:
        return parse_expr(key).to_hogql()
    except HogQLSyntaxError as error:
        raise ValidationError({"keys": f"Invalid HogQL join key: {error}"}) from error


def _capture(user: Optional[User], team: Team, event: str, proposal: RelationshipProposal) -> None:
    if user is None:
        return
    report_user_action(
        user=user,
        event=event,
        team=team,
        properties={
            "proposal_id": str(proposal.id),
            "status": proposal.status,
            "source_table": proposal.source_table_name,
            "joining_table": proposal.joining_table_name,
        },
    )


def _validate_tables_exist(team: Team, user: Optional[User], *table_names: str) -> None:
    database = Database.create_for(team_id=team.id, user=user)
    for name in table_names:
        if not database.has_table(name):
            raise ValidationError({"table": f"Table '{name}' not found. Check system.information_schema.tables."})


def propose_relationship(
    *,
    team: Team,
    user: Optional[User],
    source_table_name: str,
    source_table_key: str,
    joining_table_name: str,
    joining_table_key: str,
    field_name: str,
    configuration: Optional[dict] = None,
    confidence: Optional[float] = None,
    reasoning: str = "",
    evidence: Optional[dict] = None,
) -> RelationshipProposal:
    # Propose-time existence check so hallucinated/typo'd tables never reach the review queue.
    _validate_tables_exist(team, user, source_table_name, joining_table_name)

    fingerprint = _fingerprint(source_table_name, source_table_key, joining_table_name, joining_table_key)
    existing = RelationshipProposal.objects.for_team(team.id).filter(undirected_fingerprint=fingerprint).first()
    if existing is not None:
        raise CatalogConflict(
            detail=f"A proposal for this join pair already exists (status: {existing.status}).",
            extra={"proposal_id": str(existing.id)},
        )

    try:
        proposal = RelationshipProposal.objects.for_team(team.id).create(
            team=team,
            source_table_name=source_table_name,
            source_table_key=source_table_key,
            joining_table_name=joining_table_name,
            joining_table_key=joining_table_key,
            field_name=field_name,
            configuration=configuration or {},
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence or {},
            undirected_fingerprint=fingerprint,
            created_by=user,
        )
    except IntegrityError:
        # A concurrent reverse-orientation proposal won the fingerprint (the DB constraint kills the
        # race the logic check alone cannot).
        existing = RelationshipProposal.objects.for_team(team.id).filter(undirected_fingerprint=fingerprint).first()
        raise CatalogConflict(
            detail="A proposal for this join pair already exists.",
            extra={"proposal_id": str(existing.id) if existing else None},
        )

    _capture(user, team, "data catalog relationship proposed", proposal)
    return proposal


def accept_proposal(proposal: RelationshipProposal, user: Optional[User]) -> RelationshipProposal:
    with transaction.atomic():
        # Serialize concurrent accepts of this proposal.
        proposal = RelationshipProposal.objects.for_team(proposal.team_id).select_for_update().get(pk=proposal.pk)
        if proposal.status == RelationshipStatus.ACCEPTED and proposal.created_join_id:
            return proposal
        if proposal.status == RelationshipStatus.REJECTED:
            raise ValidationError({"status": "This proposal was rejected and cannot be accepted."})

        _acquire_accessor_lock(proposal)
        existing_join = _get_exact_existing_join(proposal)
        _probe_join(proposal, user, existing_join=existing_join)
        join = existing_join or _create_join(proposal, user)

        proposal.status = RelationshipStatus.ACCEPTED
        proposal.reviewed_by = user
        proposal.reviewed_at = timezone.now()
        proposal.created_join = join
        proposal.save()

    _capture(user, proposal.team, "data catalog relationship accepted", proposal)
    return proposal


def _probe_join(
    proposal: RelationshipProposal, user: Optional[User], *, existing_join: Optional[DataWarehouseJoin]
) -> None:
    """Prove the join works by running SELECT {joined_field} FROM {source} LIMIT 10 through it."""
    database = Database.create_for(team_id=proposal.team_id, user=user)
    from_field = get_join_field_chain(proposal.source_table_key)
    to_field = get_join_field_chain(proposal.joining_table_key)
    if from_field is None or to_field is None:
        raise ValidationError({"keys": "Join keys must be field expressions."})

    try:
        source_table = database.get_table(proposal.source_table_name)
        joining_table = database.get_table(proposal.joining_table_name)
        existing_field = source_table.fields.get(proposal.field_name)
        if existing_field is not None and existing_join is None:
            raise ValidationError(
                {"field_name": f"'{proposal.field_name}' is already a field on '{proposal.source_table_name}'."}
            )
        # Mirror the resolver selection Database uses when it materializes the real join, so the
        # probe exercises the same code path -- otherwise an experiments-optimized join is probed with
        # the plain equality resolver and an invalid experiments_timestamp_key survives review.
        configuration = proposal.configuration if isinstance(proposal.configuration, dict) else {}
        use_experiments = bool(proposal.joining_table_name == "events" and configuration.get("experiments_optimized"))
        source_table.fields["_catalog_probe"] = LazyJoin(
            from_field=from_field,
            to_field=to_field,
            join_table=joining_table,
            resolver=DATA_WAREHOUSE_EXPERIMENTS if use_experiments else DATA_WAREHOUSE,
            resolver_params=data_warehouse_resolver_params(
                source_table_key=proposal.source_table_key,
                joining_table_key=proposal.joining_table_key,
                joining_table_name=proposal.joining_table_name,
                configuration=proposal.configuration,
                override_join_type="INNER JOIN",
            ),
        )
        validation_query = parse_select(
            "SELECT {to_field} FROM {source_table_name} LIMIT 10",
            placeholders={
                "to_field": ast.Field(chain=["_catalog_probe", *to_field]),
                "source_table_name": parse_expr(proposal.source_table_name),
            },
        )
        tag_queries(product=Product.WAREHOUSE, feature=Feature.QUERY)
        execute_hogql_query(
            query=validation_query, team=proposal.team, context=HogQLContext(database=database, user=user)
        )
    except ValidationError:
        raise
    except ExposedHogQLError as e:
        raise ValidationError({"join": f"The join does not work: {e}"})
    except Exception as e:
        capture_exception(e)
        raise ValidationError({"join": "The join could not be validated against the data."})


def _acquire_accessor_lock(proposal: RelationshipProposal) -> None:
    lock_key = f"data-catalog-relationship:{proposal.team_id}:{proposal.source_table_name}:{proposal.field_name}"
    lock_id = int.from_bytes(hashlib.sha256(lock_key.encode()).digest()[:8], byteorder="big", signed=True)
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])


def _get_exact_existing_join(proposal: RelationshipProposal) -> Optional[DataWarehouseJoin]:
    joins = list(
        DataWarehouseJoin.objects.filter(
            team_id=proposal.team_id, source_table_name=proposal.source_table_name, field_name=proposal.field_name
        ).exclude(deleted=True)
    )
    exact_matches = [
        join
        for join in joins
        if join.source_table_key == proposal.source_table_key
        and join.joining_table_name == proposal.joining_table_name
        and join.joining_table_key == proposal.joining_table_key
        and _normalize_configuration(join.configuration) == _normalize_configuration(proposal.configuration)
    ]
    if len(exact_matches) == len(joins):
        return exact_matches[0] if exact_matches else None
    if joins:
        raise ValidationError(
            {"field_name": f"'{proposal.field_name}' is already a join field on '{proposal.source_table_name}'."}
        )
    return None


def _normalize_configuration(configuration: object) -> object:
    return configuration if isinstance(configuration, dict) else {}


def _create_join(proposal: RelationshipProposal, user: Optional[User]) -> DataWarehouseJoin:
    return DataWarehouseJoin.objects.create(
        team=proposal.team,
        source_table_name=proposal.source_table_name,
        source_table_key=proposal.source_table_key,
        joining_table_name=proposal.joining_table_name,
        joining_table_key=proposal.joining_table_key,
        field_name=proposal.field_name,
        configuration=proposal.configuration,
        created_by=user,
    )


def reject_proposal(proposal: RelationshipProposal, user: Optional[User], reason: str = "") -> RelationshipProposal:
    with transaction.atomic():
        proposal = RelationshipProposal.objects.for_team(proposal.team_id).select_for_update().get(pk=proposal.pk)
        if proposal.status == RelationshipStatus.REJECTED:
            return proposal
        if proposal.status != RelationshipStatus.PROPOSED:
            raise ValidationError({"status": "Only proposed relationships can be rejected."})
        proposal.status = RelationshipStatus.REJECTED
        proposal.reviewed_by = user
        proposal.reviewed_at = timezone.now()
        proposal.rejection_reason = reason
        proposal.save()

    _capture(user, proposal.team, "data catalog relationship rejected", proposal)
    return proposal


def relationships_for_team(team: Team) -> QuerySet[RelationshipProposal]:
    return RelationshipProposal.objects.for_team(team.id).order_by("-created_at")
