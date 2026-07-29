import jwt from 'jsonwebtoken'
import supertest from 'supertest'
import express from 'ultimate-express'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { GatewayAuth } from './auth'
import { CredentialCache } from './cache'
import { IntegrationDecryptor } from './crypto'
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
    let decryptor: IntegrationDecryptor
    let teamId: number

    const buildApp = (maxBatchSize = 100): express.Express => {
        const repository = new IntegrationRepository(hub.postgres)
        const service = new IntegrationService(repository, decryptor, new CredentialCache(30, 1000), null)
        const app = express()
        app.use(express.json())
        app.use('/', createGatewayRouter({ service, auth: new GatewayAuth(SECRET), maxBatchSize }))
        return app
    }

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        decryptor = new IntegrationDecryptor([SALT], [], [])
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
            sensitive_config: { access_token: decryptor.encryptLeaf('xoxb-secret-token'), not_encrypted: 'plain' },
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

    it('renders a row owned by a different team as null (not distinguishable from missing)', async () => {
        const team = await getTeam(hub.postgres, 2)
        const otherTeam = await createTeam(hub.postgres, team!.organization_id)
        const integration = await insertIntegration(hub.postgres, otherTeam, {
            kind: 'slack',
            sensitive_config: { access_token: decryptor.encryptLeaf('x') },
        })

        const res = await supertest(buildApp())
            .post('/api/v1/credentials/fetch')
            .set('authorization', `Bearer ${mint(teamId)}`)
            .send({ integration_ids: [integration.id] })

        expect(res.status).toBe(200)
        expect(res.body.integrations).toHaveProperty(String(integration.id))
        expect(res.body.integrations[String(integration.id)]).toBeNull()
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
