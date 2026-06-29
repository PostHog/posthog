import type { Pool } from 'pg'

import { PgSkillStore } from './skill-store'

const ROW = {
    id: 'uuid-1',
    name: 'triage',
    description: 'Decide which tickets need a human.',
    body: 'The triage body.',
    license: '',
    compatibility: '',
    allowed_tools: ['@posthog/memory-read'],
    metadata: { author: 'ben' },
    version: 2,
}

/** A pg.Pool stand-in whose `query` is driven by a handler keyed on the SQL. */
function fakePool(handler: (sql: string, params: unknown[]) => { rows: unknown[] }): {
    pool: Pool
    calls: { sql: string; params: unknown[] }[]
} {
    const calls: { sql: string; params: unknown[] }[] = []
    const pool = {
        query: async (sql: string, params: unknown[]) => {
            calls.push({ sql, params })
            return handler(sql, params)
        },
    } as unknown as Pool
    return { pool, calls }
}

describe('PgSkillStore.resolve', () => {
    it('resolves the latest version and renders a SKILL.md (frontmatter + body)', async () => {
        const { pool, calls } = fakePool((sql) => (sql.includes('is_latest') ? { rows: [ROW] } : { rows: [] }))
        const md = await new PgSkillStore(pool).resolve(7, 'triage')

        expect(calls[0].params).toEqual([7, 'triage'])
        expect(md).not.toBeNull()
        const body = md as string
        expect(body).toContain('name: "triage"')
        expect(body).toContain('description: "Decide which tickets need a human."')
        expect(body).toContain('  author: "ben"')
        expect(body).toContain('  version: "2"')
        expect(body).toContain('allowed-tools: @posthog/memory-read')
        // body follows the fence + a blank line
        expect(body.endsWith('---\n\nThe triage body.')).toBe(true)
    })

    it('queries a specific version when pinned', async () => {
        const { pool, calls } = fakePool(() => ({ rows: [{ ...ROW, version: 3 }] }))
        const md = await new PgSkillStore(pool).resolve(7, 'triage', 3)
        expect(calls[0].sql).toContain('version = $3')
        expect(calls[0].params).toEqual([7, 'triage', 3])
        expect(md).toContain('  version: "3"')
    })

    it('omits empty license/compatibility but includes them when set', async () => {
        const { pool } = fakePool(() => ({ rows: [{ ...ROW, license: 'MIT', compatibility: 'claude' }] }))
        const md = (await new PgSkillStore(pool).resolve(7, 'triage')) as string
        expect(md).toContain('license: "MIT"')
        expect(md).toContain('compatibility: "claude"')

        const { pool: bare } = fakePool(() => ({ rows: [ROW] }))
        const md2 = (await new PgSkillStore(bare).resolve(7, 'triage')) as string
        expect(md2).not.toContain('license:')
        expect(md2).not.toContain('compatibility:')
    })

    it('returns a companion file body when `file` is given', async () => {
        const { pool, calls } = fakePool((sql) =>
            sql.includes('llm_analytics_llmskillfile') ? { rows: [{ content: '# API' }] } : { rows: [ROW] }
        )
        const out = await new PgSkillStore(pool).resolve(7, 'triage', undefined, 'references/api.md')
        expect(out).toBe('# API')
        expect(calls[1].params).toEqual([ROW.id, 'references/api.md'])
    })

    it('returns null when the skill is missing', async () => {
        const { pool } = fakePool(() => ({ rows: [] }))
        expect(await new PgSkillStore(pool).resolve(7, 'ghost')).toBeNull()
    })

    it('returns null when the companion file is missing', async () => {
        const { pool } = fakePool((sql) =>
            sql.includes('llm_analytics_llmskillfile') ? { rows: [] } : { rows: [ROW] }
        )
        expect(await new PgSkillStore(pool).resolve(7, 'triage', undefined, 'nope.md')).toBeNull()
    })
})
