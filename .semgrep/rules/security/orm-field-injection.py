from django.db.models import Q, QuerySet

# === SHOULD BE CAUGHT (ruleid) ===


def unvalidated_filter_key(queryset: QuerySet, key: str, value: str):
    # ruleid: orm-field-injection
    return queryset.filter(**{f"{key}__icontains": value})


def unvalidated_exclude_key(queryset: QuerySet, key: str, value: str):
    # ruleid: orm-field-injection
    return queryset.exclude(**{f"{key}__in": [value]})


def unvalidated_q_key(key: str, value: str):
    # ruleid: orm-field-injection
    return Q(**{f"{key}": value})


def unvalidated_nested_key(queryset: QuerySet, field: str, operator: str, value: str):
    # ruleid: orm-field-injection
    return queryset.filter(**{f"column__{field}__{operator}": value})


# === SHOULD NOT BE CAUGHT (ok) ===


def hardcoded_key(queryset: QuerySet, value: str):
    # ok: orm-field-injection
    return queryset.filter(**{"name__icontains": value})


def hardcoded_fstring_no_var(queryset: QuerySet, value: str):
    # ok: orm-field-injection
    return queryset.filter(**{f"name__icontains": value})


def safe_explicit_kwargs(queryset: QuerySet, value: str):
    # ok: orm-field-injection
    return queryset.filter(name__icontains=value)
