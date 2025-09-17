import json
import hashlib
from typing import Any

from django.db import models, transaction
from django.forms.models import model_to_dict

from posthog.models.element import Element
from posthog.models.team import Team


def hash_elements(elements: list) -> str:
    elements_list: list[dict] = []
    for element in elements:
        el_dict = model_to_dict(element)
        [el_dict.pop(key) for key in ["event", "id", "group"]]
        elements_list.append(el_dict)
    return hashlib.md5(json.dumps(elements_list, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class ElementGroupManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        elements = kwargs.pop("elements")
        with transaction.atomic():
            for index, element in enumerate(elements):
                element.order = index
            kwargs["hash"] = hash_elements(elements)
            try:
                with transaction.atomic():
                    group = super().create(*args, **kwargs)
            except:
                return ElementGroup.objects.get(
                    hash=kwargs["hash"],
                    team_id=kwargs["team"].pk if kwargs.get("team") else kwargs["team_id"],
                )
            for element in elements:
                element.group = group
                element.pk = None
            Element.objects.bulk_create(elements)
            return group


class ElementGroup(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    hash = models.CharField(max_length=400, null=True, blank=True)

    objects = ElementGroupManager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "hash"], name="unique hash for each team")]
