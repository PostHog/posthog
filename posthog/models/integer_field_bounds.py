from django.db import connection

# Presentation serializers cannot import models, so they restate the column bounds from here.
INTEGER_FIELD_MIN, INTEGER_FIELD_MAX = connection.ops.integer_field_range("IntegerField")
BIG_INTEGER_FIELD_MIN, BIG_INTEGER_FIELD_MAX = connection.ops.integer_field_range("BigIntegerField")
