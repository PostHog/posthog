import { closeHub, createHub } from '~/common/utils/db/hub'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { insertHogFlowActionTemplate } from '../../_tests/fixtures'
import { HogFlowActionTemplateManagerService } from './hogflow-action-template-manager.service'

describe('HogFlowActionTemplateManager', () => {
    jest.setTimeout(5000)
    let hub: Hub
    let manager: HogFlowActionTemplateManagerService
    let teamId: number

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new HogFlowActionTemplateManagerService(hub.postgres, hub.pubSub, hub.encryptedFields)
        const team = await getTeam(hub.postgres, 2)
        teamId = await createTeam(hub.postgres, team!.organization_id)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('fetches a template and decrypts its encrypted inputs', async () => {
        const { id } = await insertHogFlowActionTemplate(hub.postgres, teamId, {
            template_id: 'template-webhook',
            name: 'Billing webhook',
            inputs: { url: { value: 'https://example.com' } },
            encrypted_inputs: hub.encryptedFields.encrypt(JSON.stringify({ api_key: { value: 'super-secret' } })),
        })

        const template = await manager.getHogFlowActionTemplate(id)

        expect(template?.name).toBe('Billing webhook')
        expect(template?.inputs).toEqual({ url: { value: 'https://example.com' } })
        // encrypted_inputs is decrypted into an object, not left as the ciphertext string
        expect(template?.encrypted_inputs).toEqual({ api_key: { value: 'super-secret' } })
    })

    it('excludes deleted templates', async () => {
        const { id } = await insertHogFlowActionTemplate(hub.postgres, teamId, {
            template_id: 'template-webhook',
            deleted: true,
        })
        expect(await manager.getHogFlowActionTemplate(id)).toBeNull()
    })

    it('returns null for an unknown id', async () => {
        expect(await manager.getHogFlowActionTemplate('00000000-0000-0000-0000-000000000000')).toBeNull()
    })
})
