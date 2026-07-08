import { describe, expect, it } from 'vitest'

import { AgentSpecSchema } from '../spec/spec'
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
    // The author slice must carry EXACTLY the canonical top-level fields minus
    // the server-derived `skills`/`tools`. Enforcing exact parity (not just a
    // superset) catches drift in both directions:
    //   - a new canonical field with no author passthrough → PUT /spec strict-
    //     rejects it with "Unrecognized key" and the runtime never sees a valid
    //     spec;
    //   - a stray author-only key with no canonical counterpart → dead cruft
    //     that freeze silently strips anyway (the `auth` field that used to be
    //     here).
    const SERVER_DERIVED = new Set(['skills', 'tools'])

    it('carries exactly the canonical author-facing top-level fields', () => {
        const canonicalAuthorKeys = Object.keys(AgentSpecSchema.shape)
            .filter((k) => !SERVER_DERIVED.has(k))
            .sort()
        const authorKeys = Object.keys(TypedSpecSchema.shape).sort()
        expect(authorKeys).toEqual(canonicalAuthorKeys)
    })

    it('still rejects unknown keys', () => {
        expect(TypedSpecSchema.safeParse({ not_a_real_field: 1 }).success).toBe(false)
    })
})
