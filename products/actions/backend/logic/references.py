"""The resources of other products that use an action, read through those products' facades."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from posthog.dataclasses import frozen
from posthog.models import User

from products.actions.backend.facade.contracts import ActionCreator, ActionReference, ActionReferenceType
from products.cdp.backend.facade import api as cdp_api
from products.cohorts.backend.facade import api as cohorts_api
from products.experiments.backend.facade.actions import (
    count_experiments_referencing_actions,
    experiments_referencing_action,
)
from products.product_analytics.backend.facade import api as product_analytics_api

# The most references one action lists, across every resource type.
REFERENCE_CAP = 50


@frozen
class _Found:
    type: ActionReferenceType
    id: str
    name: str
    url: str
    created_at: datetime | None
    created_by_id: int | None


def _creators(user_ids: set[int]) -> dict[int, ActionCreator]:
    if not user_ids:
        return {}
    return {
        user.id: ActionCreator(
            id=user.id,
            uuid=user.uuid,
            distinct_id=user.distinct_id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            is_email_verified=user.is_email_verified,
            hedgehog_config=user.hedgehog_config,
            role_at_organization=user.role_at_organization,
        )
        for user in User.objects.filter(id__in=user_ids)
    }


def _search(*, team_id: int, project_id: int, action_id: int) -> list[_Found]:
    """Insights first, then experiments, cohorts and hog functions, until the cap is reached."""
    found = [
        _Found(
            type="insight",
            id=str(insight.short_id),
            name=insight.name or insight.derived_name or "Unnamed",
            url=f"/insights/{insight.short_id}",
            created_at=insight.created_at,
            created_by_id=insight.created_by_id,
        )
        for insight in product_analytics_api.insights_referencing_action(
            team_id=team_id, action_id=action_id, limit=REFERENCE_CAP
        )
    ]
    if len(found) >= REFERENCE_CAP:
        return found

    found += [
        _Found(
            type="experiment",
            id=str(experiment.id),
            name=experiment.name or "Unnamed",
            url=f"/experiments/{experiment.id}",
            created_at=experiment.created_at,
            created_by_id=experiment.created_by.id if experiment.created_by is not None else None,
        )
        for experiment in experiments_referencing_action(team_id, action_id, limit=REFERENCE_CAP - len(found))
    ]
    if len(found) >= REFERENCE_CAP:
        return found

    found += [
        _Found(
            type="cohort",
            id=str(cohort.id),
            name=cohort.name or "Unnamed",
            url=f"/cohorts/{cohort.id}",
            created_at=cohort.created_at,
            created_by_id=cohort.created_by_id,
        )
        for cohort in cohorts_api.cohorts_referencing_action(
            project_id=project_id, action_id=action_id, limit=REFERENCE_CAP - len(found)
        )
    ]
    if len(found) >= REFERENCE_CAP:
        return found

    found += [
        _Found(
            type="hog_function",
            id=str(hog_function.id),
            name=hog_function.name or "Unnamed",
            url=f"/functions/{hog_function.id}",
            created_at=hog_function.created_at,
            created_by_id=hog_function.created_by_id,
        )
        for hog_function in cdp_api.hog_functions_referencing_action(
            team_id=team_id, action_id=action_id, limit=REFERENCE_CAP - len(found)
        )
    ]
    return found


def find(*, team_id: int, project_id: int, action_id: int) -> list[ActionReference]:
    found = _search(team_id=team_id, project_id=project_id, action_id=action_id)
    creators = _creators({item.created_by_id for item in found if item.created_by_id is not None})
    return [
        ActionReference(
            type=item.type,
            id=item.id,
            name=item.name,
            url=item.url,
            created_at=item.created_at,
            created_by=creators.get(item.created_by_id) if item.created_by_id is not None else None,
        )
        for item in found
    ]


def count(*, team_id: int, project_id: int, action_ids: Sequence[int]) -> dict[int, int]:
    if not action_ids:
        return {}
    counts: Counter[int] = Counter()
    counts.update(product_analytics_api.count_insights_referencing_actions(team_id=team_id, action_ids=action_ids))
    counts.update(count_experiments_referencing_actions(team_id, action_ids))
    counts.update(cohorts_api.count_cohorts_referencing_actions(project_id=project_id, action_ids=action_ids))
    counts.update(cdp_api.count_hog_functions_referencing_actions(team_id=team_id, action_ids=action_ids))
    return dict(counts)
