import { describe, expect, it } from 'vitest'

import { deriveSkillDescription } from './typed-bundle'

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
