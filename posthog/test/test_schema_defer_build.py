# posthog/schema.py defers pydantic core-schema building to first use (see
# bin/patch-schema-defer-build.py). Validation triggers a lazy build, but pydantic-core's
# serializer does not: dumping a never-validated instance nested inside another model's
# Any-typed field hits the Rust serializer fallback, which raises
# TypeError: 'MockValSer' object cannot be converted to 'SchemaSerializer'
# instead of building. That exact failure (query-runner responses carrying constructed
# models through Any-typed fields) got a previous defer_build attempt reverted. The
# guards in the generated base classes (model_construct / __setstate__) close the two
# ways an unvalidated instance can exist; these tests would fail if a schema
# regeneration or patch-script change ever dropped them.
#
# Each scenario runs in a fresh subprocess: within one process the first validation of a
# class builds it permanently, so an in-process test could never observe the unbuilt
# state these guards protect against.

import sys
import pickle
import subprocess
from pathlib import Path

from parameterized import parameterized

from posthog.schema import EventsNode

from posthog.schema_build import _deferred_model_classes, build_all_schema_models

REPO_ROOT = Path(__file__).parent.parent.parent

CONSTRUCT_THEN_DUMP = """
from posthog.schema import EventsNode
node = EventsNode.model_construct(event="pageview")
assert node.model_dump()["event"] == "pageview"
assert '"pageview"' in node.model_dump_json()
"""

NESTED_UNVALIDATED_THROUGH_ANY = """
from posthog.schema import EventsNode, QueryStatus
status = QueryStatus(id="x", team_id=1)  # validated parent with Any-typed `results`
status.results = [EventsNode.model_construct(event="pageview")]  # never-validated child
assert status.model_dump()["results"][0]["event"] == "pageview"
assert '"pageview"' in status.model_dump_json()
"""

ROOT_MODEL_CONSTRUCT_THEN_DUMP = """
from posthog.schema import SchemaRoot
root = SchemaRoot.model_construct(root={"a": 1})
assert root.model_dump() == {"a": 1}
assert root.model_dump_json() == '{"a":1}'
"""

VALIDATOR_CREATED_CHILD_THROUGH_ANY = """
from posthog.schema import QueryStatus, TrendsQuery
# Validating a parent from raw dicts makes the parent's validator construct the child
# instances; without the model_rebuild reachable-graph completion the child classes stay
# unbuilt and dumping them through an Any field raises the MockValSer TypeError. This is
# the query-runner shape that 500ed trends endpoints.
query = TrendsQuery.model_validate({"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "x"}]})
status = QueryStatus(id="x", team_id=1)
status.results = [query.series[0]]
assert status.model_dump()["results"][0]["event"] == "x"
assert '"x"' in status.model_dump_json()
"""

TYPEADAPTER_CREATED_INSTANCE_THROUGH_ANY = """
from pydantic import TypeAdapter
from posthog.schema import EventsNode, QueryStatus
# TypeAdapter builds its schema inline (temporal's pydantic payload converter does this),
# so its validator constructs instances without completing the class — the
# __get_pydantic_core_schema__ hook must complete it.
nodes = TypeAdapter(list[EventsNode]).validate_python([{"kind": "EventsNode", "event": "x"}])
status = QueryStatus(id="x", team_id=1)
status.results = nodes
assert status.model_dump()["results"][0]["event"] == "x"
"""

UNPICKLE_THEN_NESTED_DUMP = """
import pickle, sys
from posthog.schema import QueryStatus
child = pickle.loads(sys.stdin.buffer.read())  # EventsNode never built in this process
status = QueryStatus(id="x", team_id=1)
status.results = [child]
assert status.model_dump()["results"][0]["event"] == "pageview"
"""


class TestDeferredSchemaSerialization:
    def _run_fresh_process(self, snippet: str, stdin: bytes | None = None) -> None:
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=REPO_ROOT,
            input=stdin,
            capture_output=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr.decode()

    @parameterized.expand(
        [
            ("construct_then_dump", CONSTRUCT_THEN_DUMP),
            ("nested_unvalidated_through_any", NESTED_UNVALIDATED_THROUGH_ANY),
            ("root_model_construct_then_dump", ROOT_MODEL_CONSTRUCT_THEN_DUMP),
            ("validator_created_child_through_any", VALIDATOR_CREATED_CHILD_THROUGH_ANY),
            ("typeadapter_created_instance_through_any", TYPEADAPTER_CREATED_INSTANCE_THROUGH_ANY),
        ]
    )
    def test_unvalidated_instance_serializes(self, _name: str, snippet: str) -> None:
        self._run_fresh_process(snippet)

    def test_unpickled_instance_serializes_in_fresh_process(self) -> None:
        # Celery-style: an instance validated (and its class built) in one process is
        # unpickled in another where the class was never built, then dumped nested.
        self._run_fresh_process(UNPICKLE_THEN_NESTED_DUMP, stdin=pickle.dumps(EventsNode(event="pageview")))

    def test_build_all_schema_models_leaves_nothing_deferred(self) -> None:
        # Web pods rely on this covering every model (wsgi/asgi call it pre-fork).
        build_all_schema_models()
        assert list(_deferred_model_classes()) == []
