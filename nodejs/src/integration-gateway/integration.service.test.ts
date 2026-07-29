import { EncryptedFields } from '~/common/utils/encryption-utils'

import { CredentialCache } from './cache'
import { IntegrationService } from './integration.service'
import { RefreshManager } from './refresh/manager'
import { IntegrationRepository } from './repository'
import { IntegrationRow } from './types'

const SALT = '00beef0000beef0000beef0000beef00'

function makeRow(overrides: Partial<IntegrationRow> = {}): IntegrationRow {
    return { id: 1, team_id: 100, kind: 'hubspot', config: {}, sensitive_config: {}, ...overrides }
}

describe('IntegrationService team scoping', () => {
    const encryptedFields = new EncryptedFields(SALT)

    const build = (rows: IntegrationRow[]) => {
        const repository = { fetchByIds: jest.fn().mockResolvedValue(rows) } as unknown as IntegrationRepository
        const refresh = {
            owns: jest.fn(() => true),
            refresh: jest.fn((row: IntegrationRow) => Promise.resolve(row)),
        } as unknown as jest.Mocked<RefreshManager>
        const service = new IntegrationService(repository, encryptedFields, new CredentialCache(30, 100), refresh)
        return { service, refresh }
    }

    it('never refreshes or resolves an integration owned by another team', async () => {
        const { service, refresh } = build([makeRow({ id: 1, team_id: 100 })])

        // Caller is team 200; the row belongs to team 100.
        const outcome = await service.getForTeam(200, [1])

        expect(outcome.resolved.has(1)).toBe(false)
        // Critically: no cross-team refresh (an outbound OAuth call + DB write) is triggered.
        expect(refresh.refresh).not.toHaveBeenCalled()
    })

    it('refreshes and resolves an integration owned by the caller team', async () => {
        const { service, refresh } = build([makeRow({ id: 1, team_id: 100 })])

        const outcome = await service.getForTeam(100, [1])

        expect(outcome.resolved.has(1)).toBe(true)
        expect(refresh.refresh).toHaveBeenCalledTimes(1)
    })
})
