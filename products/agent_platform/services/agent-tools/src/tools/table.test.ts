/**
 * Table-tool shared-space tests — exercise the @posthog/table-* tools' `space`
 * arg against a real S3JsonlTabularStore (SeaweedFS). Focus: grant resolution
 * (read vs read_write) and that scope stays limited per (team, space) — a space
 * table is invisible across teams and separate from the agent's private tables.
 * No skip-if-unreachable; bring up SeaweedFS before running.
 */
import { S3Client } from '@aws-sdk/client-s3'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    buildTestS3Client,
    HttpClient,
    newTestPrefix,
    S3JsonlTabularStore,
    TEST_S3_BUCKET,
    type ToolContext,
    wipeTestPrefix,
} from '@posthog/agent-shared'

import { tableAppendV1, tableCountV1, tableDeleteV1, tableMembershipV1, tableQueryV1 } from './table'

interface Envelope {
    ok: boolean
    error?: string
    code?: string
    data?: Record<string, unknown>
}

describe('table tools — shared memory space access (real S3 / SeaweedFS)', () => {
    let client: S3Client
    let store: S3JsonlTabularStore
    let prefix: string

    const SPACE = 'team-tables'

    const ctxFor = (
        applicationId: string,
        grants: [string, { access: 'read' | 'read_write' }][],
        teamId = 42
    ): ToolContext => ({
        teamId,
        applicationId,
        sessionId: 'sess-1',
        secret: () => undefined,
        secretAllowedHosts: () => undefined,
        log: () => undefined,
        tabularStore: store,
        memorySpaceGrants: new Map(grants),
        http: new HttpClient(),
        posthogApiBaseUrl: 'http://localhost:8010',
    })

    beforeAll(() => {
        prefix = newTestPrefix('agent_table_tools_test')
        client = buildTestS3Client()
        store = new S3JsonlTabularStore({ client, bucket: TEST_S3_BUCKET, bucketPrefix: prefix, maxRetries: 30 })
    })

    afterEach(async () => {
        await wipeTestPrefix(client, prefix)
    })

    afterAll(async () => {
        await wipeTestPrefix(client, prefix)
        client.destroy()
    })

    it('a read_write grantee appends to a space; a read grantee (different agent) queries it back', async () => {
        const append = (await tableAppendV1.run(
            { table: 'seen', rows: [{ id: 'a' }, { id: 'b' }], space: SPACE },
            ctxFor('writer', [[SPACE, { access: 'read_write' }]])
        )) as Envelope
        expect(append.ok).toBe(true)

        const query = (await tableQueryV1.run(
            { table: 'seen', space: SPACE },
            ctxFor('reader', [[SPACE, { access: 'read' }]])
        )) as Envelope
        expect(query.ok).toBe(true)
        expect((query.data as { count: number }).count).toBe(2)
    })

    it('denies read of an ungranted space', async () => {
        const query = (await tableQueryV1.run({ table: 'seen', space: SPACE }, ctxFor('reader', []))) as Envelope
        expect(query.ok).toBe(false)
        expect(query.code).toBe('access_denied')
    })

    it('a read-only grant cannot append or delete in the space', async () => {
        const append = (await tableAppendV1.run(
            { table: 'seen', rows: [{ id: 'a' }], space: SPACE },
            ctxFor('reader', [[SPACE, { access: 'read' }]])
        )) as Envelope
        expect(append.ok).toBe(false)
        expect(append.code).toBe('access_denied')

        const del = (await tableDeleteV1.run(
            { table: 'seen', where: { id: 'a' }, space: SPACE },
            ctxFor('reader', [[SPACE, { access: 'read' }]])
        )) as Envelope
        expect(del.ok).toBe(false)
        expect(del.code).toBe('access_denied')
    })

    it('a space table is team-scoped — another team sees nothing under the same slug', async () => {
        await tableAppendV1.run(
            { table: 'seen', rows: [{ id: 'a' }], space: SPACE },
            ctxFor('writer', [[SPACE, { access: 'read_write' }]], 42)
        )
        // Same space slug + same table, DIFFERENT team → isolated by teamId.
        const count = (await tableCountV1.run(
            { table: 'seen', space: SPACE },
            ctxFor('reader', [[SPACE, { access: 'read' }]], 7)
        )) as Envelope
        expect(count.ok).toBe(true)
        expect((count.data as { count: number }).count).toBe(0)
    })

    it('a space table is separate from the agent private tables (no space arg)', async () => {
        await tableAppendV1.run(
            { table: 'seen', rows: [{ id: 'a' }], space: SPACE },
            ctxFor('writer', [[SPACE, { access: 'read_write' }]])
        )
        // Membership against the agent's OWN (private) table — the space rows must
        // not appear, so 'a' is reported as new.
        const membership = (await tableMembershipV1.run(
            { table: 'seen', key_column: 'id', values: ['a'] },
            ctxFor('writer', [[SPACE, { access: 'read_write' }]])
        )) as Envelope
        expect(membership.ok).toBe(true)
        expect((membership.data as { new: string[] }).new).toEqual(['a'])
    })
})
