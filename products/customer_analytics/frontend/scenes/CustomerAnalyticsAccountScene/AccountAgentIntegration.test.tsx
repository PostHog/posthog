import { act, cleanup, render, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { maxMocks } from 'scenes/max/testUtils'

import { attachedContextLogic } from '~/layout/ai/attachedContextLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { accountsPresenceCreate, accountsRetrieve } from 'products/customer_analytics/frontend/generated/api'
import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'
import { toolStreamEventsLogic } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/api/types'

import { AccountAgentIntegration } from './AccountAgentIntegration'
import { customerAnalyticsAccountSceneLogic } from './customerAnalyticsAccountSceneLogic'

jest.mock('products/customer_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/customer_analytics/frontend/generated/api'),
    accountsPresenceCreate: jest.fn(),
    accountsRetrieve: jest.fn(),
}))

const mockAccountsRetrieve = jest.mocked(accountsRetrieve)

const PROJECT_ID = 999
const ACCOUNT_ID = '0190da51-0b0e-7000-8000-000000000001'
const account: AccountApi = {
    id: ACCOUNT_ID,
    name: 'Example account',
    tags: [],
    notebooks: [],
    ignored_at: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
}

function accountUpdateCall(source: ToolStreamEvent['source']): ToolStreamEvent {
    return {
        streamKey: 'run-1',
        toolCallId: `update-${source}`,
        toolName: 'accounts-partial-update',
        rawToolName: 'exec',
        phase: 'completed',
        source,
        invocation: {
            toolCallId: `update-${source}`,
            rawServerName: 'posthog',
            rawToolName: 'exec',
            input: { command: `call accounts-partial-update {"id":"${ACCOUNT_ID}","tags":["renewal"]}` },
            status: 'completed',
            contentBlocks: [],
        },
    }
}

describe('AccountAgentIntegration', () => {
    const sceneProps = { accountId: ACCOUNT_ID, projectId: PROJECT_ID }
    let logic: ReturnType<typeof customerAnalyticsAccountSceneLogic.build>

    beforeEach(async () => {
        useMocks(maxMocks)
        initKeaTests()
        jest.mocked(accountsPresenceCreate).mockResolvedValue([])
        mockAccountsRetrieve.mockResolvedValue(account)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN]: true,
            [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
        })
        logic = customerAnalyticsAccountSceneLogic(sceneProps)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        render(
            <BindLogic logic={customerAnalyticsAccountSceneLogic} props={sceneProps}>
                <AccountAgentIntegration account={account} />
            </BindLogic>
        )
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('attaches the open account as a reference the user can see', () => {
        expect(attachedContextLogic.values.contextItems.filter((item) => !item.hidden)).toEqual([
            expect.objectContaining({ type: 'customer_analytics_account', key: ACCOUNT_ID, label: 'Example account' }),
        ])
    })

    it('refreshes the open account after a live agent change, and not when history replays it', async () => {
        const savedAccount: AccountApi = { ...account, tags: ['renewal'] }
        mockAccountsRetrieve.mockClear().mockResolvedValue(savedAccount)

        act(() => {
            toolStreamEventsLogic.actions.emitToolEvent(accountUpdateCall('replay'))
        })
        expect(mockAccountsRetrieve).not.toHaveBeenCalled()

        act(() => {
            toolStreamEventsLogic.actions.emitToolEvent(accountUpdateCall('live'))
        })
        await waitFor(() => expect(logic.values.account).toEqual(savedAccount))
    })
})
