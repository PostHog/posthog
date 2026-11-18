from django.db.models import BigIntegerField, Func


# Callers pass fixed model fields; Django compiles them into the static SQL template without user input.
# nosemgrep: python.django.security.audit.extends-custom-expression.extends-custom-expression
class JsonByteLength(Func):
    function = "OCTET_LENGTH"
    template = "COALESCE(%(function)s((%(expressions)s)::text), 0)"
    output_field = BigIntegerField()
    arity = 1
