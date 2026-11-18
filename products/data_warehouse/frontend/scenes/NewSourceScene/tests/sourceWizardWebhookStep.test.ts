import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import type { ExternalDataSourceSyncSchema } from '~/types'

import type { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { sourceWizardLogic, WIZARD_DESTINATION_STEP } from '../sourceWizardLogic'

// Separate from sourceWizardLogic.test.ts: running createSource to completion there corrupts a memoized selector.
describe('sourceWizardLogic webhook step', () => {
    beforeEach(() => {
        initKeaTests()
    })

    const webhookSource = {
        name: 'Stripe',
        caption: '',
        fields: [],
        label: 'Stripe',
        iconPath: '',
        docsUrl: '',
        existingSource: false,
        unreleasedSource: false,
    } as unknown as SourceConfigResponseApi

    const webhookSchema = {
        table: 'charges',
        should_sync: true,
        sync_type: 'webhook',
        supports_webhooks: true,
    } as ExternalDataSourceSyncSchema

    it.each([
        { name: 'with the destination step', startStep: WIZARD_DESTINATION_STEP },
        { name: 'without the destination step', startStep: 3 },
    ])('sends a webhook source to the webhook step $name', async ({ startStep }) => {
        const logic = sourceWizardLogic({ availableSources: { Stripe: webhookSource } })
        const unmount = logic.mount()
        jest.spyOn(api.externalDataSources, 'create').mockResolvedValue({ id: 'test-webhook-source' } as Awaited<
            ReturnType<typeof api.externalDataSources.create>
        >)
        jest.spyOn(api.productIntents, 'update').mockResolvedValue(MOCK_DEFAULT_TEAM)

        try {
            await expectLogic(logic, () => logic.actions.selectConnector(webhookSource)).toFinishAllListeners()
            logic.actions.setDatabaseSchemas([webhookSchema])
            logic.actions.setStep(startStep)

            await expectLogic(logic, () => logic.actions.createSource()).toFinishAllListeners()

            expect(logic.values.currentStep).toEqual(4)
        } finally {
            jest.restoreAllMocks()
            unmount()
        }
    })
})
