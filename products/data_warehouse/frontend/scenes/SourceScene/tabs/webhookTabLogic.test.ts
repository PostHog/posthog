import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import type { ExternalDataSource, WebhookInfo } from '~/types'

import type { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { sourceSettingsLogic } from './sourceSettingsLogic'
import { webhookTabLogic } from './webhookTabLogic'

jest.mock('lib/api')

const SOURCE_ID = 'source-1'

// Mirrors Mailgun: the signing key sits in the vendor dashboard before the webhook exists, so
// the tab collects it and sends it with the create call.
const SOURCE_CONFIG = {
    name: 'Mailgun',
    label: 'Mailgun',
    fields: [],
    webhookFieldsBeforeCreate: true,
    webhookFields: [
        {
            type: 'password',
            name: 'signing_secret',
            label: 'HTTP webhook signing key',
            required: true,
            secret: true,
        },
    ],
} as unknown as SourceConfigResponseApi

const webhookInfo = (exists: boolean): WebhookInfo => ({ supports_webhooks: true, exists })

describe('webhookTabLogic', () => {
    let logic: ReturnType<typeof webhookTabLogic.build>
    let settingsLogic: ReturnType<typeof sourceSettingsLogic.build>

    const mountWith = async (exists: boolean): Promise<void> => {
        jest.spyOn(api.externalDataSources, 'wizard').mockResolvedValue({ Mailgun: SOURCE_CONFIG })
        jest.spyOn(api.externalDataSources, 'get').mockResolvedValue({
            id: SOURCE_ID,
            source_type: 'Mailgun',
            schemas: [],
        } as unknown as ExternalDataSource)
        jest.spyOn(api.externalDataSources, 'jobs').mockResolvedValue([])
        jest.spyOn(api.externalDataSources, 'getWebhookInfo').mockResolvedValue(webhookInfo(exists))

        settingsLogic = sourceSettingsLogic({ id: SOURCE_ID, availableSources: {} })
        settingsLogic.mount()
        logic = webhookTabLogic({ id: SOURCE_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(settingsLogic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        settingsLogic?.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        [false, { signing_secret: 'HTTP webhook signing key is required' }],
        [true, {}],
    ])(
        'a blank signing key passes validation only once the webhook exists (exists: %s)',
        async (exists, expectedErrors) => {
            await mountWith(exists)

            expect(logic.values.sourceConfig?.webhookFields).toHaveLength(1)
            expect(logic.values.webhookFieldInputsValidationErrors).toEqual(expectedErrors)
        }
    )
})
