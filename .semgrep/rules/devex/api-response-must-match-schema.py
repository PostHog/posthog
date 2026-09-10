# Test cases for api-response-must-match-schema rule.
# ruff: noqa: F841, E501

from rest_framework.response import Response


# ============================================================
# Should flag: viewset returns hand-assembled data dict
# ============================================================


def list_things():
    # ruleid: api-response-must-match-schema
    return Response({"things": [1, 2, 3]})


def detail_thing():
    # ruleid: api-response-must-match-schema
    return Response({"id": 1, "name": "foo"})


def detail_with_data_kwarg():
    # ruleid: api-response-must-match-schema
    return Response(data={"id": 1, "name": "foo"})


# ============================================================
# Should NOT flag: conventional DRF error/ack idioms
# ============================================================


def not_found():
    # ok: api-response-must-match-schema
    return Response({"detail": "Not found"}, status=404)


def not_found_data_kwarg():
    # ok: api-response-must-match-schema
    return Response(data={"detail": "Not found"}, status=404)


def bad_request():
    # ok: api-response-must-match-schema
    return Response({"error": "bad input"}, status=400)


def ack():
    # ok: api-response-must-match-schema
    return Response({"success": True})


def paginated():
    # ok: api-response-must-match-schema
    return Response({"results": [], "count": 0, "next": None, "previous": None})


# ============================================================
# Should NOT flag: payload constructed via serializer
# ============================================================


class FooSerializer:
    pass


def correct_pattern(foo):
    # ok: api-response-must-match-schema
    return Response(FooSerializer(instance=foo).data)
