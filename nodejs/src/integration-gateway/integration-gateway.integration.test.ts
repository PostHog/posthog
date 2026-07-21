import jwt from 'jsonwebtoken'
import supertest from 'supertest'
import express from 'ultimate-express'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { EncryptedFields } from '~/cdp/utils/encryption-utils'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { GatewayAuth } from './auth'
import { CredentialCache } from './cache'
import { IntegrationService } from './integration.service'
import { IntegrationRepository } from './repository'
import { createGatewayRouter } from './router'

const AUDIENCE = 'posthog:integration_gateway'
const SECRET = 'test-secret'
const SALT = '00beef0000beef0000beef0000beef00'

function mint(teamId: number): string {
    return jwt.sign({ team_id: teamId, caller: 'test' }, SECRET, { audience: AUDIENCE, expiresIn: 300 })
}

describe('integration gateway credential API', () => {
    let hub: Hub
    let encryptedFields: EncryptedFields
    let teamId: number

    // A cache is shared across requests to one app so the cache-hit test can observe staleness.
    const buildApp = (maxBatchSize = 100, cache = new CredentialCache(30, 1000)): express.Express => {
        const service = new IntegrationService(new IntegrationRepository(hub.postgres), encryptedFields, cache, null)
        const app = express()
        app.use(express.json())
        app.use('/', createGatewayRouter({ service, auth: new GatewayAuth(SECRET), maxBatchSize }))
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
            .set('authorization', `Bearer ${mint(teamId)}`)
            .send({ integration_ids: [integration.id] })

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
        const owned = await insertIntegration(hub.postgres, teamId, {
            kind: 'slack',
            sensitive_config: { access_token: encryptedFields.encrypt('mine') },
        })
        const otherTeamsRow = await insertIntegration(hub.postgres, otherTeam, {
            kind: 'slack',
            sensitive_config: { access_token: encryptedFields.encrypt('theirs') },
        })
        const missingId = 999999

        const res = await supertest(buildApp())
            .post('/api/v1/credentials/fetch')
            .set('authorization', `Bearer ${mint(teamId)}`)
            .send({ integration_ids: [owned.id, otherTeamsRow.id, missingId] })

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
            .set('authorization', `Bearer ${mint(teamId)}`)
            .send({ integration_ids: [integration.id] })
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
            .set('authorization', `Bearer ${mint(teamId)}`)
            .send({ integration_ids: [integration.id] })
        expect(second.body.integrations[String(integration.id)].sensitive_config.access_token).toBe('first')
    })

    it.each([
        ['a bad token', 'Bearer not-a-jwt'],
        ['no token', null],
    ])('rejects %s with 401', async (_name, header) => {
        const request = supertest(buildApp()).post('/api/v1/credentials/fetch')
        if (header) {
            request.set('authorization', header)
        }
        const res = await request.send({ integration_ids: [1] })
        expect(res.status).toBe(401)
    })

    it('rejects a batch larger than the configured max with 400', async () => {
        const res = await supertest(buildApp(1))
            .post('/api/v1/credentials/fetch')
            .set('authorization', `Bearer ${mint(teamId)}`)
            .send({ integration_ids: [1, 2] })
        expect(res.status).toBe(400)
    })
})
