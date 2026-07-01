import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { APPROVAL_REQUEST_STATES } from '../persistence/approval-store'
import { TRIGGER_REQUIRED_SECRETS } from './trigger-secrets'

/**
 * Cross-language bridge for spec vocabularies Django needs as data. Each value is
 * authored once in TS and *emitted* as a checked-in JSON that Python *imports*, so
 * there's no hand-maintained Python copy to keep in lockstep. Adding a vocabulary
 * is one entry in `GENERATED_ARTIFACTS`; freshness is guarded by
 * `spec-codegen.test.ts`. Regenerate after editing any source:
 *
 *   UPDATE_GENERATED=1 npx vitest run src/spec/spec-codegen.test.ts
 */

export interface GeneratedArtifact {
    /** Absolute path of the emitted file — in the Django tree next to its Python
     *  consumer, mirroring how generated frontend types live under `frontend/generated/`. */
    path: string
    /** Canonical bytes: 4-space indent + trailing newline to match oxfmt (the repo
     *  JSON formatter), so the committed file survives lint-staged untouched and the
     *  byte-for-byte freshness comparison stays meaningful. */
    content: () => string
}

const backendLogic = (name: string): string =>
    join(dirname(fileURLToPath(import.meta.url)), '../../../../backend/logic', name)

const asJson = (value: unknown): string => `${JSON.stringify(value, null, 4)}\n`

export const GENERATED_ARTIFACTS: GeneratedArtifact[] = [
    {
        path: backendLogic('trigger_required_secrets.generated.json'),
        content: () => asJson(TRIGGER_REQUIRED_SECRETS),
    },
    {
        path: backendLogic('approval_request_states.generated.json'),
        content: () => asJson(APPROVAL_REQUEST_STATES),
    },
]
