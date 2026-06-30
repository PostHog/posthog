import { describe, expect, it } from 'vitest'

import { AgentSpecObjectSchema } from '../spec/spec'
import { deriveSkillDescription, TypedSpecSchema } from './typed-bundle'

describe('deriveSkillDescription', () => {
    it.each([
        [
            'frontmatter description wins (not the --- fence)',
            '---\nname: triage-playbook\ndescription: Structured triage flow — load when starting an investigation.\n---\n\n# Skill\n\nbody',
            'Structured triage flow — load when starting an investigation.',
        ],
        [
            'no frontmatter falls back to first prose line',
            '# Runbook memory\n\nYour durable knowledge lives in agent memory.',
            'Your durable knowledge lives in agent memory.',
        ],
        [
            'frontmatter without a description falls back to body prose, not the block',
            '---\nname: x\ntags: a, b\n---\n\n# Heading\n\nFirst real line.',
            'First real line.',
        ],
        ['surrounding quotes are stripped', '---\ndescription: "Quoted value."\n---\nbody', 'Quoted value.'],
        ['empty body yields empty string', '', ''],
    ])('%s', (_label, raw, expected) => {
        expect(deriveSkillDescription(raw)).toBe(expected)
    })

    it('caps the description at 280 chars', () => {
        const long = 'x'.repeat(400)
        expect(deriveSkillDescription(`---\ndescription: ${long}\n---\n`)).toHaveLength(280)
    })
})

describe('TypedSpecSchema ↔ AgentSpec key parity', () => {
    // `skills`/`tools` are server-derived at freeze, so the author slice
    // intentionally omits them. Everything else on the canonical schema must
    // be passed through, or the strict authoring API rejects it at PUT /spec
    // with "Unrecognized key" while the runtime never sees a valid spec — the
    // exact failure mode `authoritative_provider` hit. This test fails the
    // moment someone adds a top-level field to AgentSpecSchema without a
    // matching passthrough in TypedSpecSchema.
    const SERVER_DERIVED = new Set(['skills', 'tools'])

    it('passes through every canonical author-facing top-level field', () => {
        const canonicalAuthorKeys = Object.keys(AgentSpecObjectSchema.shape).filter((k) => !SERVER_DERIVED.has(k))
        const authorKeys = new Set(Object.keys(TypedSpecSchema.shape))
        const missing = canonicalAuthorKeys.filter((k) => !authorKeys.has(k))
        expect(missing).toEqual([])
    })

    it('accepts authoritative_provider and still rejects unknown keys', () => {
        expect(TypedSpecSchema.safeParse({ authoritative_provider: 'posthog' }).success).toBe(true)
        expect(TypedSpecSchema.safeParse({ not_a_real_field: 1 }).success).toBe(false)
    })
})
