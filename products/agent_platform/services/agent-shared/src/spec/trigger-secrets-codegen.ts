import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { TRIGGER_REQUIRED_SECRETS } from './trigger-secrets'

/**
 * Cross-language bridge for the per-trigger required-secrets registry.
 *
 * `TRIGGER_REQUIRED_SECRETS` (trigger-secrets.ts) is the single authored home —
 * typed `Record<TriggerType, …>`, so it's total by construction on the TS side.
 * The Django promote gate needs the same contract, but a hand-maintained Python
 * copy is exactly the drift hazard Django already retired for the spec schema
 * (see `backend/logic/spec_schema.py`). So instead of a second copy kept in sync
 * by convention, TS *emits* the registry as a checked-in JSON that Python
 * *imports*. There is then no parity to assert — one source, one derived artifact.
 *
 * The freshness of the emitted file is guarded by `trigger-secrets-codegen.test.ts`
 * (same-tree: TS object vs the JSON it produced — not a cross-language source
 * scrape). Regenerate after editing the registry:
 *
 *   UPDATE_GENERATED=1 npx vitest run src/spec/trigger-secrets-codegen.test.ts
 */

/** Absolute path of the generated file — lives next to its Python consumer in the
 *  Django tree, mirroring how generated frontend types live under `frontend/generated/`. */
export const GENERATED_JSON_PATH = join(
    dirname(fileURLToPath(import.meta.url)),
    '../../../../backend/logic/trigger_required_secrets.generated.json'
)

/** Canonical JSON projection of the TS registry: stable (authored) key order,
 *  4-space indent + trailing newline to match oxfmt (the repo JSON formatter), so
 *  the committed artifact survives lint-staged untouched and a byte-for-byte
 *  freshness comparison stays meaningful. */
export function serializeTriggerSecrets(): string {
    return `${JSON.stringify(TRIGGER_REQUIRED_SECRETS, null, 4)}\n`
}
