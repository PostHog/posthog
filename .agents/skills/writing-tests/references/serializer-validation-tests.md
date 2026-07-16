# DRF input-validation tests: SimpleTestCase, not APIBaseTest

A test that posts a malformed body to an endpoint and asserts a 400 pays for `APIBaseTest` to build an Organization + Team + User in Postgres and wrap the test in a transaction — just to exercise validation that runs entirely in memory.

DRF field validators (`required`, type coercion, `choices`, `min/max`, regex) and `validate_<field>` methods run inside `Serializer(data=...).is_valid()` with no database and no request: field-level validation happens in `to_internal_value`, _before_ the object-level `validate()` that typically needs `self.context`. So an invalid-field case never reaches the DB-touching code.

Test the serializer directly and assert on `.errors`:

```python
class TestTeamValidation(SimpleTestCase):  # no DB — not APIBaseTest
    def test_sample_rate_too_many_digits(self) -> None:
        s = TeamSerializer(data={"session_recording_sample_rate": "30001"}, partial=True)
        assert not s.is_valid()
        assert s.errors["session_recording_sample_rate"][0].code == "max_digits"
```

## Keep one wiring guard at the endpoint

When you push the case matrix down to the serializer, **keep (or add) one DB-backed endpoint test as a wiring guard** — that the viewset actually invokes this serializer, so a bad request is rejected with a 400.
The no-DB serializer test proves the validation logic; it does _not_ prove the viewset is wired to that serializer (a refactor that drops the `serializer_class`, skips `is_valid()`, or stops calling `is_valid(raise_exception=True)` would pass every `SimpleTestCase` and still ship a broken endpoint).
One endpoint case closes that gap; the matrix stays in the `SimpleTestCase`.
For a query serializer instantiated inline (e.g. `Serializer(data=request.query_params).is_valid(raise_exception=True)`), the wiring guard is a bad-query-param → 400 assertion.

## Caveats

- `.errors` carries DRF's _raw_ code (`invalid`, `max_digits`); the `{"attr", "code", "detail", "type"}` HTTP envelope is rendered later by `exceptions-hog` (which maps `invalid` → `invalid_input`).
  That rendering is framework behavior — don't re-assert it per case; the wiring-guard test covers the envelope once.
- Validation that genuinely needs the DB stays at the endpoint — uniqueness checks, `PrimaryKeyRelatedField` queryset lookups, related-object existence, permission/team scoping, password-hash checks. Don't force those into a `SimpleTestCase`.
