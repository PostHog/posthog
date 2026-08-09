import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import { sourceSettingsLogic } from './sourceSettingsLogic'
import { webhookTabLogic } from './webhookTabLogic'

jest.mock('lib/api')

describe('webhookTabLogic', () => {
    let logic: ReturnType<typeof webhookTabLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()

        jest.spyOn(api.externalDataSources, 'wizard').mockResolvedValue({
            Stripe: { name: 'Stripe', label: 'Stripe', caption: '', fields: [] },
        } as any)
        jest.spyOn(api.externalDataSources, 'get').mockResolvedValue({
            id: 'source-1',
            source_type: 'Stripe',
            schemas: [],
        } as unknown as ExternalDataSource)
        jest.spyOn(api.externalDataSources, 'jobs').mockResolvedValue([])
        jest.spyOn(api.externalDataSources, 'getWebhookInfo').mockResolvedValue({ exists: false } as any)
    })

    afterEach(() => {
        logic?.unmount()
        featureFlagLogic.unmount()
        jest.restoreAllMocks()
    })

    // Guards the fix for the `[KEA] Can not find path "...sourceSettingsLogic.<id>"` toast: the tab
    // must mount sourceSettingsLogic through connect, not read its selectors off an unmounted store.
    it('reads source and sourceConfig through a mounted sourceSettingsLogic', async () => {
        logic = webhookTabLogic({ id: 'source-1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        const settingsLogic = sourceSettingsLogic.findMounted({ id: 'source-1' })
        expect(settingsLogic).toBeTruthy()
        expect(logic.values.source?.id).toEqual('source-1')
        expect(logic.values.sourceConfig?.name).toEqual('Stripe')
        // Shared state through connect, not a copy read off the store.
        expect(logic.values.source).toBe(settingsLogic!.values.source)
    })
})
