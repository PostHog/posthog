import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { kindSpec, knownKinds, validateStructure } from '@posthog/sdk/stack'

// The engine declares each kind's naming rule in its mapping file, and check enforces the same rule
// before anything is sent. This test fails when the two say different things.
const mappings = fileURLToPath(new URL('../../../products/stacks/backend/engine/mapping/', import.meta.url))
const files = readdirSync(mappings).filter((name) => name.endsWith('.json'))

// Kinds the engine doesn't manage, so no mapping file states their rule.
const WITHOUT_MAPPING = new Set([])

test('every mapping file has a kind in the registry', () => {
    assert.deepEqual(
        files.map((name) => name.replace(/\.json$/, '')).filter((kind) => !kindSpec(kind)),
        []
    )
})

for (const name of files) {
    const kind = name.replace(/\.json$/, '')
    test(`the ${kind} key rule is the same in the registry and the engine's mapping`, () => {
        const mapping = JSON.parse(readFileSync(`${mappings}${name}`, 'utf8'))
        const natural = mapping.natural_key && mapping.natural_key.definition_key !== false
        const rule = kindSpec(kind)?.naturalKey
        if (!natural) {
            assert.equal(rule, undefined)
            return
        }
        assert.deepEqual(
            {
                field: rule?.field,
                pattern: rule?.pattern,
                maxLength: rule?.maxLength,
                reserved: rule?.reserved ?? [],
                reservedPrefixes: rule?.reservedPrefixes ?? [],
            },
            {
                field: mapping.natural_key.field,
                pattern: mapping.key_pattern,
                maxLength: mapping.key_max_length,
                reserved: mapping.reserved_keys ?? [],
                reservedPrefixes: mapping.reserved_key_prefixes ?? [],
            }
        )
    })
}

test('every natural-key kind in the registry has a mapping, or is known to have none', () => {
    const missing = knownKinds().filter(
        (kind) => kindSpec(kind)?.naturalKey && !files.includes(`${kind}.json`) && !WITHOUT_MAPPING.has(kind)
    )
    assert.deepEqual(missing, [])
})

const keyCodes = (kind, key, field = kindSpec(kind).naturalKey.field) =>
    validateStructure({ version: 1, resources: [{ kind, key, body: { [field]: key } }] })
        .filter((problem) => problem.code.startsWith('key_'))
        .map((problem) => problem.code)

for (const [kind, key, codes] of [
    ['event', 'checkout completed', []],
    ['event', '工具栏已加载', []],
    ['event', ' checkout', ['key_invalid']],
    ['event', 'checkout\u0000', ['key_invalid']],
    ['event', '😀'.repeat(400), []],
    ['event', '😀'.repeat(401), ['key_invalid']],
    ['model', '$mrr.v2', []],
    ['model', 'system.events', ['key_invalid']],
    ['model', 'models', ['key_invalid']],
    ['endpoint', 'last_execution_times', ['key_invalid']],
    ['endpoint', '9lives', ['key_invalid']],
    ['metric', 'bulk_delete', ['key_invalid']],
    ['metric', 'total-mrr', ['key_invalid']],
]) {
    test(`a ${kind} named ${JSON.stringify(key.slice(0, 24))} gives ${JSON.stringify(codes)}`, () => {
        assert.deepEqual(keyCodes(kind, key), codes)
    })
}
