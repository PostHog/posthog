import json

from posthog.models.property import Property


def get_operator(prop: Property, arg: str):
    operator = prop.operator

    if operator == "is_not":
        return "(trim(BOTH '\"' FROM ep.value) = %({})s)".format(arg), prop.value
    elif operator == "icontains" or operator == "not_icontains":
        value = "%{}%".format(prop.value)
        return "(trim(BOTH '\"' FROM ep.value) LIKE %({})s)".format(arg), value
    elif operator == "regex" or operator == "not_regex":
        return "match(trim(BOTH '\"' FROM ep.value), %({})s)".format(arg), prop.value
    elif operator == "is_set":
        return "", prop.value
    elif operator == "is_not_set":
        return "", prop.value
    elif operator == "gt":
        return (
            "(toInt64(trim(BOTH '\"' FROM ep.value)) >  %({})s)".format(arg),
            prop.value,
        )
    elif operator == "lt":
        return (
            "(toInt64(trim(BOTH '\"' FROM ep.value)) <  %({})s)".format(arg),
            prop.value,
        )
    else:
        if is_json(prop.value):
            return (
                "replaceRegexpAll(trim(BOTH '\"' FROM ep.value),' ', '') = replaceRegexpAll(toString(%({})s),' ', '')".format(
                    arg
                ),
                prop.value,
            )
        else:
            return (
                "(trim(BOTH '\"' FROM ep.value) = toString(%({})s))".format(arg),
                prop.value,
            )


def is_json(val):
    if isinstance(val, int):
        return False

    try:
        json.loads(val)
    except ValueError:
        return False
    return True
