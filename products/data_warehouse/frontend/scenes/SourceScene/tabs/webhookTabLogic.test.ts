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

const webhookInfo = (exists: boolean, overrides: Partial<WebhookInfo> = {}): WebhookInfo => ({
    supports_webhooks: true,
    exists,
    ...overrides,
})

describe('webhookTabLogic', () => {
    let logic: ReturnType<typeof webhookTabLogic.build>
    let settingsLogic: ReturnType<typeof sourceSettingsLogic.build>

    const mountWith = async (exists: boolean, infoOverrides: Partial<WebhookInfo> = {}): Promise<void> => {
        jest.spyOn(api.externalDataSources, 'wizard').mockResolvedValue({ Mailgun: SOURCE_CONFIG })
        jest.spyOn(api.externalDataSources, 'get').mockResolvedValue({
            id: SOURCE_ID,
            source_type: 'Mailgun',
            schemas: [],
        } as unknown as ExternalDataSource)
        jest.spyOn(api.externalDataSources, 'jobs').mockResolvedValue([])
        jest.spyOn(api.externalDataSources, 'getWebhookInfo').mockResolvedValue(webhookInfo(exists, infoOverrides))

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

    // One form serves the first create, the re-create after the provider webhook is deleted, and a
    // plain credential rotation. Only the last one is an input update: routing either of the other
    // two to `updateWebhookInputs` stores the key and leaves the provider with nothing to deliver
    // from, so no data arrives and the tab still looks set up.
    it.each([
        ['no delivery function yet', false, {}, 'createWebhook'],
        ['the provider webhook is gone', true, { external_status: { exists: false } }, 'createWebhook'],
        ['both sides exist', true, { external_status: { exists: true } }, 'updateWebhookInputs'],
    ])(
        'submitting the credential form calls %s -> %s',
        async (_name, exists, infoOverrides, expectedCall) => {
            await mountWith(exists, infoOverrides as Partial<WebhookInfo>)

            const createWebhook = jest
                .spyOn(api.externalDataSources, 'createWebhook')
                .mockResolvedValue({ success: true, webhook_url: 'https://example.com/w/1' })
            const updateWebhookInputs = jest
                .spyOn(api.externalDataSources, 'updateWebhookInputs')
                .mockResolvedValue(undefined as never)

            logic.actions.setWebhookFieldInputsValue('signing_secret', 'key-from-the-vendor-dashboard')
            logic.actions.submitWebhookFields()
            await expectLogic(logic).toFinishAllListeners()

            expect(createWebhook).toHaveBeenCalledTimes(expectedCall === 'createWebhook' ? 1 : 0)
            expect(updateWebhookInputs).toHaveBeenCalledTimes(expectedCall === 'updateWebhookInputs' ? 1 : 0)
        }
    )
})
