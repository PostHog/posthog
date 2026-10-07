import { resetContext } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { accountViewsList, accountViewsPartialUpdate, userCustomerAnalyticsConfigRetrieve } from '../../generated/api'
import type { AccountViewApi } from '../../generated/api.schemas'
import { createAccountViewContent, parseAccountViewContent } from './accountViewDocument'
import { accountViewsLogic } from './accountViewsLogic'

jest.mock('../../generated/api', () => ({
    accountViewsList: jest.fn(),
    accountViewsPartialUpdate: jest.fn(),
    userCustomerAnalyticsConfigRetrieve: jest.fn(),
}))
const mockList = jest.mocked(accountViewsList)
const mockUpdate = jest.mocked(accountViewsPartialUpdate)
const firstConfig = { properties: [{ kind: 'account', key: 'website_domain' }] }
const secondConfig = {
    properties: [
        { kind: 'account', key: 'known_emails' },
        { kind: 'relationship', id: '22222222-2222-4222-8222-222222222222' },
    ],
}

describe('accountViewsLogic properties tiles', () => {
    let logic: ReturnType<typeof accountViewsLogic.build>
    let view: AccountViewApi
    beforeEach(() => {
        resetContext()
        jest.clearAllMocks()
        view = {
            id: '11111111-1111-4111-8111-111111111111',
            name: 'Account view',
            visibility: 'private',
            version: 1,
            created_by: 1,
            last_modified_by: 1,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
            can_edit: true,
            can_delete: true,
            can_change_visibility: true,
            text_content: 'Properties\nProperties\nNotes',
            content: createAccountViewContent([
                { nodeId: 'first', kind: 'properties', span: 6, config: firstConfig },
                { nodeId: 'second', kind: 'properties', span: 6, config: secondConfig },
                { nodeId: 'notes', kind: 'notes', span: 12, config: { searchTerm: 'Existing search' } },
            ]),
        }
        mockList.mockImplementation(async () => [view])
        mockUpdate.mockImplementation(async (_, __, patch) => {
            view = { ...view, content: patch.content ?? view.content, version: view.version + 1 }
            return view
        })
        jest.mocked(userCustomerAnalyticsConfigRetrieve).mockResolvedValue({
            pinned_properties: [],
            task_digest: { enabled: false, send_time: '09:00', cadence: 'weekdays' },
            account_detail_tabs: { ordered_tab_ids: [], hidden_tab_ids: [], default_tab_id: null },
        })
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]: true })
        logic = accountViewsLogic({ projectId: 1 })
        logic.mount()
    })
    afterEach(() => {
        logic.unmount()
        featureFlagLogic.unmount()
    })

    it('retains the configuration after a failed save and retries without changing another tile or sidebar pins', async () => {
        await expectLogic(logic).toFinishAllListeners()
        const changed = { properties: [...secondConfig.properties].reverse() }
        logic.actions.openTileEditor(view.id, 'first', 'Properties', {
            propertiesConfig: firstConfig,
            accountId: 'account-one',
        })
        logic.actions.setTileEditorPropertiesConfig(changed)
        mockUpdate.mockRejectedValueOnce(new Error('Save failed'))
        await expectLogic(logic, () => {
            logic.actions.saveTileEditor()
            logic.actions.saveTileEditor()
        }).toFinishAllListeners()
        expect(mockUpdate).toHaveBeenCalledTimes(1)
        expect(logic.values.tileEditor?.propertiesConfig).toEqual(changed)
        expect(logic.values.tileSaving).toBe(false)
        await expectLogic(logic, () => logic.actions.saveTileEditor()).toFinishAllListeners()
        expect(logic.values.tileEditor).toBeNull()
        const components = parseAccountViewContent(logic.values.views[0].content)
        expect(components[0].config).toEqual(changed)
        expect(components[1].config).toEqual(secondConfig)
        expect(components[2].config).toEqual({ searchTerm: 'Existing search' })
        expect(logic.values.config?.pinned_properties).toEqual([])
        await expectLogic(logic, () => logic.actions.loadViews()).toFinishAllListeners()
        expect(parseAccountViewContent(logic.values.views[0].content)).toEqual(components)
    })
})
