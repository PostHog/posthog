import { readFileSync, writeFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import { GENERATED_JSON_PATH, serializeTriggerSecrets } from './trigger-secrets-codegen'

/**
 * Generated-artifact freshness (Coherence — collapse the TS/Python copies to one).
 *
 * `TRIGGER_REQUIRED_SECRETS` is authored once in TS; Django imports the JSON this
 * emits. The only way that bridge rots is if the registry changes and the JSON
 * isn't regenerated — so this asserts the checked-in file is byte-for-byte what
 * the current TS source produces. Edit the registry without regenerating and it
 * goes red, naming the fix. This is a same-tree comparison (TS object vs the JSON
 * it produced), not a cross-language source scrape.
 *
 * Set UPDATE_GENERATED=1 to (re)write the file instead of asserting.
 */
describe('trigger-secrets generated artifact', () => {
    if (process.env.UPDATE_GENERATED) {
        writeFileSync(GENERATED_JSON_PATH, serializeTriggerSecrets())
    }

    it('checked-in JSON matches the TS registry (regenerate with UPDATE_GENERATED=1)', () => {
        const onDisk = readFileSync(GENERATED_JSON_PATH, 'utf-8')
        expect(onDisk).toBe(serializeTriggerSecrets())
    })
})
