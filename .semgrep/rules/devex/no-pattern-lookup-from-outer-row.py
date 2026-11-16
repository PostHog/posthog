# Test cases for no-pattern-lookup-from-outer-row.
# ruff: noqa

from django.db import models
from django.db.models import Exists, F, OuterRef, Q, TextField, Value, functions as db_functions
from django.db.models.functions import Cast, Concat, JSONArray, JSONArray as JsonArray, JSONObject
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
    # todook: no-pattern-lookup-from-outer-row
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

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(**{"team_id": team_id, "path__startswith": OuterRef("path")})

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(path__startswith=Concat(*[OuterRef("path"), Value("/")]))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(**{"team_id": team_id, "labels__contains": [OuterRef("label")]})

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(labels__contains=(OuterRef("label"),))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(**{"team_id": team_id, "labels__contains": (OuterRef("label"), OuterRef("tag"))})

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(path__startswith=(Concat(OuterRef("path"), Value("/"))))

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(StartsWith(lhs=F("path"), rhs=OuterRef("path")))

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.filter(StartsWith(F("path"), rhs=Concat(OuterRef("path"), Value("/"))))

# ruleid: no-pattern-lookup-from-outer-row
Task.objects.filter(labels__contains=[OuterRef("label")], path__startswith=OuterRef("path"))

# ruleid: no-pattern-lookup-from-outer-row
Task.objects.filter(**{"labels__contains": (OuterRef("label"),), "path__startswith": OuterRef("path")})


def aliased_models_import(queryset):
    from django.db import models as db_models

    # ruleid: no-pattern-lookup-from-outer-row
    return queryset.filter(path__startswith=db_models.OuterRef("path"))


FileSystem.objects.filter(
    team_id=team_id,
    # nosemgrep: no-pattern-lookup-from-outer-row -- the outer query is one row, fetched by id
    path__startswith=OuterRef("path"),
)


def list_held_in_a_variable(queryset):
    labels = [OuterRef("label")]
    # todook: no-pattern-lookup-from-outer-row
    return queryset.filter(labels__contains=labels)


def tuple_held_in_a_variable(queryset):
    labels = (OuterRef("label"), OuterRef("tag"))
    # todook: no-pattern-lookup-from-outer-row
    return queryset.filter(labels__contains=labels)


# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(Contains(F("labels"), [OuterRef("label")]))


def lookup_dict_held_in_a_variable(queryset):
    # ruleid: no-pattern-lookup-from-outer-row
    filters = {"team_id": team_id, "path__startswith": Concat(OuterRef("path"), Value("/"))}
    return queryset.filter(**filters)


def lookup_key_built_with_an_f_string(queryset, field):
    # ruleid: no-pattern-lookup-from-outer-row
    return queryset.filter(**{f"{field}__startswith": OuterRef("path")})


def parts_list_unpacked_into_concat(queryset):
    parts = [OuterRef("path"), Value("/")]
    # ruleid: no-pattern-lookup-from-outer-row
    return queryset.filter(path__startswith=Concat(*parts))


def containment_next_to_a_star_argument(queryset, conditions):
    # ok: no-pattern-lookup-from-outer-row
    return queryset.filter(*conditions, labels__contains=[OuterRef("label")])


# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(Contains(F("labels"), (OuterRef("label"),)))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(Contains(F("labels"), rhs=[OuterRef("label")]))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(Contains(lhs=F("labels"), rhs=(OuterRef("label"),)))

# ruleid: no-pattern-lookup-from-outer-row
Task.objects.filter(Contains(F("labels"), [OuterRef("label")]), StartsWith(F("path"), OuterRef("path")))

# ruleid: no-pattern-lookup-from-outer-row
Task.objects.filter(**{"labels__contains": [OuterRef("label")], "path__startswith": OuterRef("path")})

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(state__verified_urls__contains=db_functions.JSONArray(OuterRef("url")))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(state__contains=db_functions.JSONObject(url=OuterRef("url")))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(state__verified_urls__contains=JsonArray(OuterRef("url")))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(Contains(F("state"), JSONArray(OuterRef("url"))))

# ruleid: no-pattern-lookup-from-outer-row
FileSystem.objects.annotate(info=JSONObject(has_child=Exists(Task.objects.filter(path__startswith=OuterRef("path")))))

# ruleid: no-pattern-lookup-from-outer-row
Task.objects.filter(path__startswith=Cast(JSONArray(OuterRef("path")), TextField()))

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(**{"state__verified_urls__contains": JSONArray(OuterRef("url"))})

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(**{"state__contains": JSONObject(url=OuterRef("url"))})

# ok: no-pattern-lookup-from-outer-row
Task.objects.filter(Contains(F("state"), JSONObject(url=OuterRef("url"))))
