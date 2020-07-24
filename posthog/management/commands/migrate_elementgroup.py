import hashlib
import json

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from django.forms.models import model_to_dict
from django.utils import timezone

from posthog.models import Element, ElementGroup, Event


class Command(BaseCommand):
    help = "Migrate data to new model"

    def hash_elements(self, elements):
        elements_list = []
        for element in elements:
            el_dict = model_to_dict(element)
            [el_dict.pop(key) for key in ["event", "id", "group"]]
            elements_list.append(el_dict)
        return hashlib.md5(json.dumps(elements_list, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    def handle(self, *args, **options):
        hashes_seen = []
        elements_count = 0
        elements_saved = 0
        while Event.objects.filter(element__isnull=False, elements_hash__isnull=True, event="$autocapture").exists():
            with transaction.atomic():
                events = (
                    Event.objects.filter(element__isnull=False, elements_hash__isnull=True, event="$autocapture",)
                    .prefetch_related(models.Prefetch("element_set", to_attr="elements_cache"))
                    .distinct("pk")[:1000]
                )
                print("1k")
                for event in events:
                    elements = event.elements_cache
                    hash = self.hash_elements(elements)
                    event.elements_hash = hash
                    event.save()
                    elements_count += len(elements)
                    if hash not in hashes_seen:
                        try:
                            group = ElementGroup.objects.get(team_id=event.team_id, hash=hash)
                        except:
                            group = ElementGroup.objects.create(team_id=event.team_id, hash=hash, elements=elements)
                        hashes_seen.append(hash)
                    else:
                        elements_saved += len(elements)
            print("Elements seen: %s" % elements_count)
            print("Elements saved: %s" % elements_saved)
