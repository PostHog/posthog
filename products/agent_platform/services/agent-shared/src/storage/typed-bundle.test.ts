import { describe, expect, it } from 'vitest'

import type { BundleEntry, BundleStore } from './bundle'
import { deriveSkillDescription, syncBundleToStore, type TypedBundle } from './typed-bundle'

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

/** Minimal in-memory BundleStore for the full-replace sync (only list/write/
 *  delete are exercised). */
function memStore(initial: Record<string, string> = {}): BundleStore & { files: Map<string, string> } {
    const files = new Map<string, string>(Object.entries(initial))
    const store = {
        files,
        async list(): Promise<BundleEntry[]> {
            return [...files.keys()].map((path) => ({ path, size: files.get(path)!.length, sha256: '' }))
        },
        async read(_rev: string, p: string) {
            return Buffer.from(files.get(p) ?? '')
        },
        async readText(_rev: string, p: string) {
            return files.get(p) ?? ''
        },
        async write(_rev: string, p: string, content: Buffer | string) {
            files.set(p, content.toString())
        },
        async delete(_rev: string, p: string) {
            files.delete(p)
        },
        async exists(_rev: string, p: string) {
            return files.has(p)
        },
    }
    return store as unknown as BundleStore & { files: Map<string, string> }
}

function bundle(skills: TypedBundle['skills']): TypedBundle {
    return { agent_md: '# agent', skills, tools: [], spec: {} as TypedBundle['spec'] }
}

describe('syncBundleToStore', () => {
    it('writes each bundled skill body to skills/<id>/SKILL.md', async () => {
        const store = memStore()
        await syncBundleToStore('rev1', store, bundle([{ id: 'capture', description: 'd', body: '# capture' }]))
        expect(store.files.get('skills/capture/SKILL.md')).toBe('# capture')
        expect(store.files.get('agent.md')).toBe('# agent')
    })

    it('full-replace sweeps a skill folder no longer in the payload', async () => {
        const store = memStore({
            'agent.md': 'old',
            'skills/keep/SKILL.md': 'keep',
            'skills/drop/SKILL.md': 'drop',
            'skills/drop/references/x.md': 'companion',
        })
        await syncBundleToStore('rev1', store, bundle([{ id: 'keep', description: 'd', body: 'keep-new' }]))
        expect(store.files.get('skills/keep/SKILL.md')).toBe('keep-new')
        expect(store.files.has('skills/drop/SKILL.md')).toBe(false)
        expect(store.files.has('skills/drop/references/x.md')).toBe(false)
    })
})
