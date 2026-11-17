from django.db.models import BigIntegerField, Func


class JsonByteLength(Func):
    function = "OCTET_LENGTH"
    template = "COALESCE(%(function)s((%(expressions)s)::text), 0)"
    output_field = BigIntegerField()
    arity = 1
