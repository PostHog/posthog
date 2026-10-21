import { expectLogic } from 'kea-test-utils'

import { ProjectSecretAPIKeyApi } from '~/generated/core/api.schemas'
import { initKeaTests } from '~/test/init'

import { GATEWAY_SCOPE, gatewayKeySpendLogic } from './gatewayKeySpendLogic'
import { fetchGatewaySpendByCredential } from './gatewayKeySpendQuery'
import { projectSecretAPIKeysLogic } from './projectSecretAPIKeysLogic'

jest.mock('./gatewayKeySpendQuery', () => ({
    ...jest.requireActual('./gatewayKeySpendQuery'),
    fetchGatewaySpendByCredential: jest.fn(),
}))

const gatewayKey = (overrides: Partial<ProjectSecretAPIKeyApi>): ProjectSecretAPIKeyApi => ({
    id: 'key',
    label: 'Key',
    value: '',
    mask_value: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: { id: 1, uuid: 'test-user', first_name: 'Test', email: 'test@example.com', hedgehog_config: null },
    last_used_at: null,
    last_rolled_at: null,
    scopes: [GATEWAY_SCOPE],
    ai_credential: null,
    ...overrides,
})

describe('gatewayKeySpendLogic', () => {
    let logic: ReturnType<typeof gatewayKeySpendLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = gatewayKeySpendLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('joins spend to keys by ai_credential and tallies spend no current key can claim', async () => {
        jest.mocked(fetchGatewaySpendByCredential).mockResolvedValue([
            { credential: 'aaa', requests: 10, costUsd: 4 },
            { credential: 'ccc', requests: 1, costUsd: 0.5 },
            { credential: 'gone', requests: 2, costUsd: 1.5 },
            { credential: null, requests: 3, costUsd: 0.25 },
        ])

        projectSecretAPIKeysLogic.actions.loadKeysSuccess([
            gatewayKey({ id: 'a', label: 'Agent', mask_value: 'phs_...aaaa', ai_credential: 'aaa' }),
            gatewayKey({ id: 'b', label: 'Idle', ai_credential: 'bbb' }),
            gatewayKey({ id: 'c', label: 'Descoped', scopes: ['feature_flag:read'], ai_credential: 'ccc' }),
            gatewayKey({ id: 'd', label: 'Flags only', scopes: ['feature_flag:read'], ai_credential: 'ddd' }),
        ])
        await expectLogic(logic).toDispatchActions(['loadSpend', 'loadSpendSuccess'])

        expect(logic.values.summary).toEqual({
            rows: [
                { id: 'a', label: 'Agent', maskValue: 'phs_...aaaa', requests: 10, costUsd: 4 },
                { id: 'c', label: 'Descoped', maskValue: null, requests: 1, costUsd: 0.5 },
                { id: 'b', label: 'Idle', maskValue: null, requests: 0, costUsd: 0 },
            ],
            unmatchedCostUsd: 1.5,
            untaggedCostUsd: 0.25,
        })
    })

    it('does not query spend for a project with no gateway key', async () => {
        projectSecretAPIKeysLogic.actions.loadKeysSuccess([gatewayKey({ scopes: ['feature_flag:read'] })])
        await expectLogic(logic).toNotHaveDispatchedActions(['loadSpend'])

        expect(fetchGatewaySpendByCredential).not.toHaveBeenCalled()
        expect(logic.values.hasGatewayKeys).toBe(false)
    })
})
