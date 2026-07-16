# Logic

Django-side authoring logic: the promote-time secret gate and the loaders for the TS-emitted vocabulary artifacts the control plane consumes instead of hand-maintaining mirrors.

## invariants

- unregistered-trigger-fail-closed
- generated-vocabulary-loader
- artifact-ci-coverage

## works when

- typechecks
- boundary "unregistered-trigger-fail-closed" at missing_required_secrets
- passes test "test_missing_required_secrets_fails_closed_on_unregistered_trigger"
- boundary "generated-vocabulary-loader" at \_load
- passes test "test_generated_vocabularies_load_and_are_nonempty"
- boundary "artifact-ci-coverage" at TRIGGER_REQUIRED_SECRETS via test "test_ci_agents_filter_covers_every_generated_artifact"

## why

unregistered-trigger-fail-closed: the promote gate walks each trigger's required-secret contract, and a trigger type the node schema accepts but this registry doesn't know must BLOCK promote rather than pass with zero required secrets — the old `.get(type, [])` fail-open let a new trigger ship with its signing secret never enforced. `missing_required_secrets` is the single gate every promote crosses; the oracle proves an unregistered type yields a blocking entry.
generated-vocabulary-loader: every vocabulary Django consumes (trigger secrets, routes, approval states, stop reasons) loads through one `_load` that reads UTF-8 explicitly, fails closed with a legible `ImproperlyConfigured` naming the file and the regen command, and rejects wrong-shaped artifacts — a corrupt or missing generated JSON must be a clear boot-time error, not a cryptic traceback or a silent empty vocabulary.
artifact-ci-coverage: a guard only counts if CI actually invokes it — the TS freshness test that welds each generated JSON to its source runs under a CI path filter, and an artifact outside that filter can drift green. The oracle enumerates every `*.generated.json` on disk and asserts the `ci-agents` filter covers each, so adding an artifact without CI coverage is a red build naming the file.
