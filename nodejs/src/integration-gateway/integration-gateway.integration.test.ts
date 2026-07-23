import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { setupExpressApp } from '~/common/api/router'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { EncryptedFields } from '~/common/utils/encryption-utils'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { CredentialCache } from './cache'
import { IntegrationService } from './integration.service'
import { IntegrationRepository } from './repository'
import { createGatewayRouter } from './router'

const SALT = '00beef0000beef0000beef0000beef00'

describe('integration gateway credential API', () => {
    let hub: Hub
    let encryptedFields: EncryptedFields
    let teamId: number

    // ultimate-express binds its listen socket asynchronously, so supertest's lazy `app.listen(0)`
    // reads an unresolved address and throws "Invalid URL". Mirror the sibling cdp-api test: build
    // via setupExpressApp (same wiring as the real server, incl. body parsing) and listen eagerly,
    // tracking each server so afterEach can close it.
    const servers: Server[] = []

    // A cache is shared across requests to one app so the cache-hit test can observe staleness.
    const buildApp = (maxBatchSize = 100, cache = new CredentialCache(30, 1000)): express.Application => {
        const service = new IntegrationService(new IntegrationRepository(hub.postgres), encryptedFields, cache, null)
        const app = setupExpressApp()
        app.use('/', createGatewayRouter({ service, maxBatchSize }))
        servers.push(app.listen(0))
        return app
    }

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        encryptedFields = new EncryptedFields(SALT)
        const team = await getTeam(hub.postgres, 2)
        teamId = await createTeam(hub.postgres, team!.organization_id)
    })

    afterEach(async () => {
        // Best-effort, non-awaited close (matches cdp-api.test.ts): ultimate-express's server.close
        // never fires its callback, so awaiting one hangs the hook.
        for (const server of servers.splice(0)) {
            server.close()
        }
        await closeHub(hub)
    })

    it('fetches and decrypts an integration for the owning team', async () => {
        const integration = await insertIntegration(hub.postgres, teamId, {
            kind: 'slack',
            config: { team: 'T-1234' },
            sensitive_config: { access_token: encryptedFields.encrypt('xoxb-secret-token'), not_encrypted: 'plain' },
        })

        const res = await supertest(buildApp())
            .post('/api/v1/credentials/fetch')
            .send({ team_id: teamId, caller: 'test', integration_ids: [integration.id] })

        expect(res.status).toBe(200)
        const got = res.body.integrations[String(integration.id)]
        expect(got.team_id).toBe(teamId)
        expect(got.kind).toBe('slack')
        // sensitive_config is decrypted; the undecryptable leaf passes through unchanged.
        expect(got.sensitive_config.access_token).toBe('xoxb-secret-token')
        expect(got.sensitive_config.not_encrypted).toBe('plain')
        // config is returned verbatim (not encrypted).
        expect(got.config.team).toBe('T-1234')
    })

    it('resolves owned ids and renders wrong-team and missing ids as null in one batch', async () => {
        const team = await getTeam(hub.postgres, 2)
        const otherTeam = await createTeam(hub.postgres, team!.organization_id)
        // Explicit distinct ids: the fixture defaults id to 1, so two rows in one test collide on
        // the real integer primary key.
        const owned = await insertIntegration(hub.postgres, teamId, {
            id: 1,
            kind: 'slack',
            sensitive_config: { access_token: encryptedFields.encrypt('mine') },
        })
        const otherTeamsRow = await insertIntegration(hub.postgres, otherTeam, {
            id: 2,
            kind: 'slack',
            sensitive_config: { access_token: encryptedFields.encrypt('theirs') },
        })
        const missingId = 999999

        const res = await supertest(buildApp())
            .post('/api/v1/credentials/fetch')
            .send({ team_id: teamId, caller: 'test', integration_ids: [owned.id, otherTeamsRow.id, missingId] })

        expect(res.status).toBe(200)
        expect(res.body.integrations[String(owned.id)].sensitive_config.access_token).toBe('mine')
        // Wrong-team and missing are both present-as-key but null — indistinguishable on purpose.
        expect(res.body.integrations[String(otherTeamsRow.id)]).toBeNull()
        expect(res.body.integrations[String(missingId)]).toBeNull()
    })

    it('serves a cached value within TTL even after the DB row changes', async () => {
        const integration = await insertIntegration(hub.postgres, teamId, {
            kind: 'slack',
            sensitive_config: { access_token: encryptedFields.encrypt('first') },
        })
        const app = buildApp() // one app => one shared cache across both requests

        const first = await supertest(app)
            .post('/api/v1/credentials/fetch')
            .send({ team_id: teamId, caller: 'test', integration_ids: [integration.id] })
        expect(first.body.integrations[String(integration.id)].sensitive_config.access_token).toBe('first')

        // Mutate the row directly; a cache hit must still return the original value.
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_integration SET sensitive_config = jsonb_set(sensitive_config, '{access_token}', $1::jsonb) WHERE id = $2`,
            [JSON.stringify(encryptedFields.encrypt('second')), integration.id],
            'test-mutate-integration'
        )

        const second = await supertest(app)
            .post('/api/v1/credentials/fetch')
            .send({ team_id: teamId, caller: 'test', integration_ids: [integration.id] })
        expect(second.body.integrations[String(integration.id)].sensitive_config.access_token).toBe('first')
    })

    it.each([
        ['a missing team_id', { integration_ids: [1] }],
        ['a non-integer team_id', { team_id: 'nope', integration_ids: [1] }],
    ])('rejects %s with 400', async (_name, body) => {
        const res = await supertest(buildApp()).post('/api/v1/credentials/fetch').send(body)
        expect(res.status).toBe(400)
    })

    it('rejects a batch larger than the configured max with 400', async () => {
        const res = await supertest(buildApp(1))
            .post('/api/v1/credentials/fetch')
            .send({ team_id: teamId, caller: 'test', integration_ids: [1, 2] })
        expect(res.status).toBe(400)
    })
})
