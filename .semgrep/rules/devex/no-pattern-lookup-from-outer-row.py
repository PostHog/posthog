# Test cases for no-pattern-lookup-from-outer-row.
# ruff: noqa

from django.db import models
from django.db.models import Exists, F, OuterRef, Q, Value
from django.db.models.functions import Concat, JSONArray, JSONObject
from django.db.models.lookups import Contains, StartsWith

# ruleid: no-pattern-lookup-from-outer-row
children = FileSystem.objects.filter(team_id=team_id, path__startswith=Concat(OuterRef("path"), Value("/")))

# ruleid: no-pattern-lookup-from-outer-row
queryset.alias(has_children=Exists(FileSystem.objects.filter(path__istartswith=OuterRef("path"))))

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.exclude(path__contains=OuterRef("basename"))

# ruleid: no-pattern-lookup-from-outer-row
Q(name__icontains=models.OuterRef("name"))

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(path__endswith=OuterRef("basename"))

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(path__regex=OuterRef("pattern"))

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(path__unaccent__iendswith=OuterRef("basename"))

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(**{"path__startswith": OuterRef("path")})


def prefix_held_in_a_variable(queryset):
    prefix = Concat(OuterRef("path"), Value("/"))
    # ruleid: no-pattern-lookup-from-outer-row
    return queryset.filter(path__startswith=prefix)


# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(StartsWith(F("path"), OuterRef("path")))

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(Contains(F("path"), Concat(OuterRef("path"), Value("/"))))

# ok: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(path__startswith=f"{folder}/")

# ok: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(team_id=OuterRef("team_id"), type=OuterRef("type"), ref=OuterRef("ref"))

# ok: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(path__startswith=F("parent_path"))

# ok: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(path=OuterRef("path"), name__icontains=search)

# nosemgrep: no-pattern-lookup-from-outer-row -- the outer query is one row, fetched by id
FileSystem.objects.filter(path__startswith=OuterRef("path"))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(state__verified_urls__contains=JSONArray(OuterRef("url")))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(state__contains=JSONObject(url=OuterRef("url")))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(labels__contains=[OuterRef("label")])


def containment_value_held_in_a_variable(queryset):
    urls = JSONArray(OuterRef("url"))
    # ok: no-pattern-lookup-from-outer-row
    return queryset.filter(state__verified_urls__contains=urls)


def containment_wrapping_a_variable(queryset):
    url = OuterRef("url")
    # ok: no-pattern-lookup-from-outer-row
    return queryset.filter(state__verified_urls__contains=JSONArray(url))


def suffix_held_in_a_variable(queryset):
    suffix = Concat(Value("/"), OuterRef("basename"))
    # ruleid: no-pattern-lookup-from-outer-row
    return queryset.filter(path__endswith=suffix)


def qualified_outer_ref_held_in_a_variable(queryset):
    prefix = Concat(models.OuterRef("path"), Value("/"))
    # ruleid: no-pattern-lookup-from-outer-row
    return queryset.filter(path__startswith=prefix)


def variable_passed_as_an_unpacked_key(queryset):
    prefix = Concat(OuterRef("path"), Value("/"))
    # ruleid: no-pattern-lookup-from-outer-row
    return queryset.filter(**{"path__startswith": prefix})


def variable_passed_to_a_lookup_class(queryset):
    prefix = Concat(OuterRef("path"), Value("/"))
    # ruleid: no-pattern-lookup-from-outer-row
    return queryset.filter(StartsWith(F("path"), prefix))


def variable_reassigned_to_a_constant(queryset):
    prefix = Concat(OuterRef("path"), Value("/"))
    prefix = Value("fixed/")
    # ok: no-pattern-lookup-from-outer-row
    return queryset.filter(path__startswith=prefix)
