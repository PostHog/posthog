import json
from typing import Counter, Dict, List, Tuple

from django.db import models
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver
from django.forms.models import model_to_dict
from django.utils import timezone

from posthog.constants import AUTOCAPTURE_EVENT, TREND_FILTER_TYPE_ACTIONS
from posthog.models import Entity, Filter
from posthog.models.action_step import ActionStep
from posthog.models.property import Property, PropertyIdentifier
from posthog.models.utils import PersonPropertiesMode
from posthog.redis import get_client


class Action(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["team_id", "-updated_at"]),
        ]

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    description: models.TextField = models.TextField(blank=True, default="")
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE, null=True, blank=True)
    deleted: models.BooleanField = models.BooleanField(default=False)
    events: models.ManyToManyField = models.ManyToManyField("Event", blank=True)
    post_to_slack: models.BooleanField = models.BooleanField(default=False)
    slack_message_format: models.CharField = models.CharField(default="", max_length=200, blank=True)
    is_calculating: models.BooleanField = models.BooleanField(default=False)
    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    last_calculated_at: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True)

    def __str__(self):
        return self.name

    def get_analytics_metadata(self):
        return {
            "post_to_slack": self.post_to_slack,
            "name_length": len(self.name),
            "custom_slack_message_format": self.slack_message_format != "",
            "event_count_precalc": self.events.count(),  # `precalc` because events are computed async
            "step_count": self.steps.count(),
            "match_text_count": self.steps.exclude(Q(text="") | Q(text__isnull=True)).count(),
            "match_href_count": self.steps.exclude(Q(href="") | Q(href__isnull=True)).count(),
            "match_selector_count": self.steps.exclude(Q(selector="") | Q(selector__isnull=True)).count(),
            "match_url_count": self.steps.exclude(Q(url="") | Q(url__isnull=True)).count(),
            "has_properties": self.steps.exclude(properties=[]).exists(),
            "deleted": self.deleted,
        }


@receiver(post_save, sender=Action)
def action_saved(sender, instance: Action, created, **kwargs):
    get_client().publish("reload-action", json.dumps({"teamId": instance.team_id, "actionId": instance.id}))


@receiver(post_delete, sender=Action)
def action_deleted(sender, instance: Action, **kwargs):
    get_client().publish("drop-action", json.dumps({"teamId": instance.team_id, "actionId": instance.id}))


def format_action_filter(
    team_id: int,
    action: Action,
    prepend: str = "action",
    use_loop: bool = False,
    filter_by_team=True,
    table_name: str = "",
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_SUBQUERY,
) -> Tuple[str, Dict]:
    # get action steps
    params = {"team_id": action.team.pk} if filter_by_team else {}
    steps = action.steps.all()
    if len(steps) == 0:
        # If no steps, it shouldn't match this part of the query
        return "1=2", {}

    or_queries = []
    for index, step in enumerate(steps):
        conditions: List[str] = []
        # filter element
        if step.event == AUTOCAPTURE_EVENT:
            from ee.clickhouse.models.property import filter_element  # prevent circular import

            el_condition, element_params = filter_element(model_to_dict(step), prepend=f"{action.pk}_{index}{prepend}")
            params = {**params, **element_params}
            if len(el_condition) > 0:
                conditions.append(el_condition)

        # filter event conditions (ie URL)
        event_conditions, event_params = filter_event(step, f"{action.pk}_{index}{prepend}", index, table_name)
        params = {**params, **event_params}
        conditions += event_conditions

        if step.properties:
            from ee.clickhouse.models.property import parse_prop_grouped_clauses

            prop_query, prop_params = parse_prop_grouped_clauses(
                team_id=team_id,
                property_group=Filter(data={"properties": step.properties}).property_groups,
                prepend=f"action_props_{action.pk}_{step.pk}",
                table_name=table_name,
                person_properties_mode=person_properties_mode,
            )
            conditions.append(prop_query.replace("AND", "", 1))
            params = {**params, **prop_params}

        if len(conditions) > 0:
            or_queries.append(" AND ".join(conditions))
    if use_loop:
        formatted_query = "SELECT uuid FROM events WHERE {} AND team_id = %(team_id)s".format(
            ") OR uuid IN (SELECT uuid FROM events WHERE team_id = %(team_id)s AND ".join(or_queries)
        )
    else:
        formatted_query = "(({}))".format(") OR (".join(or_queries))
    return formatted_query, params


def filter_event(
    step: ActionStep, prepend: str = "event", index: int = 0, table_name: str = ""
) -> Tuple[List[str], Dict]:
    from ee.clickhouse.models.property import get_property_string_expr

    params = {"{}_{}".format(prepend, index): step.event}
    conditions = []

    if table_name != "":
        table_name += "."

    if step.url:
        value_expr, _ = get_property_string_expr("events", "$current_url", "'$current_url'", f"{table_name}properties")
        prop_name = f"{prepend}_prop_val_{index}"
        if step.url_matching == ActionStep.EXACT:
            conditions.append(f"{value_expr} = %({prop_name})s")
            params.update({prop_name: step.url})
        elif step.url_matching == ActionStep.REGEX:
            conditions.append(f"match({value_expr}, %({prop_name})s)")
            params.update({prop_name: step.url})
        else:
            conditions.append(f"{value_expr} LIKE %({prop_name})s")
            params.update({prop_name: f"%{step.url}%"})

    conditions.append(f"event = %({prepend}_{index})s")

    return conditions, params


def format_entity_filter(
    team_id: int, entity: Entity, prepend: str = "action", filter_by_team=True
) -> Tuple[str, Dict]:
    if entity.type == TREND_FILTER_TYPE_ACTIONS:
        action = entity.get_action()
        entity_filter, params = format_action_filter(
            team_id=team_id, action=action, prepend=prepend, filter_by_team=filter_by_team
        )
    else:
        key = f"{prepend}_event"
        entity_filter = f"event = %({key})s"
        params = {key: entity.id}

    return entity_filter, params


def get_action_tables_and_properties(action: Action) -> Counter[PropertyIdentifier]:
    from ee.clickhouse.models.property import extract_tables_and_properties

    result: Counter[PropertyIdentifier] = Counter()

    for action_step in action.steps.all():
        if action_step.url:
            result[("$current_url", "event", None)] += 1
        result += extract_tables_and_properties(
            Filter(data={"properties": action_step.properties or []}).property_groups.flat
        )

    return result


def uses_elements_chain(action: Action) -> bool:
    for action_step in action.steps.all():
        if any(Property(**prop).type == "element" for prop in (action_step.properties or [])):
            return True
        if any(getattr(action_step, attribute) is not None for attribute in ["selector", "tag_name", "href", "text"]):
            return True
    return False
