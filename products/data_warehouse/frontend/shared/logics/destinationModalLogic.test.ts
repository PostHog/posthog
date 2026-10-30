import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { destinationModalLogic } from './destinationModalLogic'

jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    externalDataDestinationsCreate: jest.fn(),
    externalDataDestinationsDestroy: jest.fn(),
    externalDataDestinationsPartialUpdate: jest.fn(),
}))

const wsApi = jest.requireMock('products/warehouse_sources/frontend/generated/api')

const SAVED = {
    id: 'dest-1',
    name: 'Warehouse copy',
    type: 'Postgres',
    integration: 1,
    config: {},
} as ExternalDataDestinationApi

describe('destinationModalLogic', () => {
    let logic: ReturnType<typeof destinationModalLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = destinationModalLogic({ modalKey: 'test', onSaved: () => {} })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('starts a new destination on Postgres with its defaults', async () => {
        await expectLogic(logic, () => logic.actions.openForCreate()).toFinishAllListeners()

        expect(logic.values.destinationForm).toMatchObject({
            type: 'Postgres',
            integrationKind: 'postgresql',
            database: 'postgres',
            schema: 'public',
        })
    })

    it('drops the previous type fields when the type changes', async () => {
        // Carrying them over leaves another type's values in the form. They would be dropped
        // silently at save time, so the payload would not match what the form showed.
        await expectLogic(logic, () => logic.actions.openForCreate()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.setDestinationType('BigQuery')).toFinishAllListeners()

        expect(logic.values.destinationForm.database).toBeUndefined()
        expect(logic.values.destinationForm.schema).toBeUndefined()
        expect(logic.values.destinationForm.type).toEqual('BigQuery')
    })

    it('keeps the name already typed when the type changes', async () => {
        await expectLogic(logic, () => logic.actions.openForCreate()).toFinishAllListeners()
        logic.actions.setDestinationFormValue('name', 'Warehouse copy')

        await expectLogic(logic, () => logic.actions.setDestinationType('Snowflake')).toFinishAllListeners()

        expect(logic.values.destinationForm.name).toEqual('Warehouse copy')
    })

    it('follows the type to its own connection kind', async () => {
        await expectLogic(logic, () => logic.actions.openForCreate()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.setDestinationType('Databricks')).toFinishAllListeners()

        expect(logic.values.destinationForm.integrationKind).toEqual('databricks')
    })

    it('lets a multi-kind type switch provider without changing type', async () => {
        // S3 covers AWS and every S3-compatible provider, and the connection list is per kind.
        await expectLogic(logic, () => logic.actions.openForCreate()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.setDestinationType('S3')).toFinishAllListeners()
        expect(logic.values.destinationForm.integrationKind).toEqual('aws-s3')

        await expectLogic(logic, () => logic.actions.setIntegrationKind('s3-compatible')).toFinishAllListeners()

        expect(logic.values.destinationForm.type).toEqual('S3')
        expect(logic.values.destinationForm.integrationKind).toEqual('s3-compatible')
    })

    it('reports the picked type as invalid until its own required fields are filled', async () => {
        await expectLogic(logic, () => logic.actions.openForCreate()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.setDestinationType('Snowflake')).toFinishAllListeners()

        logic.actions.setDestinationFormValue('name', 'Snowflake copy')
        logic.actions.setDestinationFormValue('integrationId', 1)
        // `database` and `warehouse` are still empty.
        expect(logic.values.isDestinationFormValid).toBe(false)

        logic.actions.setDestinationFormValue('database', 'DB')
        logic.actions.setDestinationFormValue('warehouse', 'WH')

        expect(logic.values.isDestinationFormValid).toBe(true)
    })

    it.each([
        { mode: 'create', withOnCreated: true, expectedToast: null, onCreatedCalls: 1 },
        { mode: 'create', withOnCreated: false, expectedToast: 'Destination added', onCreatedCalls: 0 },
        { mode: 'edit', withOnCreated: true, expectedToast: 'Destination updated', onCreatedCalls: 0 },
    ])(
        'picks the toast and callbacks on $mode (onCreated passed: $withOnCreated)',
        async ({ mode, withOnCreated, expectedToast, onCreatedCalls }) => {
            // The page that passes onCreated shows its own next-step toast, so the generic one must not stack on it.
            wsApi.externalDataDestinationsCreate.mockResolvedValue(SAVED)
            wsApi.externalDataDestinationsPartialUpdate.mockResolvedValue(SAVED)
            const toastSpy = jest.spyOn(lemonToast, 'success')
            const onSaved = jest.fn()
            const onCreated = jest.fn()
            const saveLogic = destinationModalLogic({
                modalKey: `save-${mode}-${withOnCreated}`,
                onSaved,
                onCreated: withOnCreated ? onCreated : undefined,
            })
            saveLogic.mount()

            if (mode === 'create') {
                await expectLogic(saveLogic, () => saveLogic.actions.openForCreate()).toFinishAllListeners()
            } else {
                await expectLogic(saveLogic, () => saveLogic.actions.openForEdit(SAVED)).toFinishAllListeners()
            }
            await expectLogic(saveLogic, () =>
                saveLogic.actions.submitDestinationFormRequest({
                    ...saveLogic.values.destinationForm,
                    name: 'Warehouse copy',
                })
            ).toFinishAllListeners()

            expect(onSaved).toHaveBeenCalledWith(SAVED)
            expect(onCreated).toHaveBeenCalledTimes(onCreatedCalls)
            if (expectedToast) {
                expect(toastSpy).toHaveBeenCalledWith(expectedToast)
            } else {
                expect(toastSpy).not.toHaveBeenCalled()
            }
            toastSpy.mockRestore()
            saveLogic.unmount()
        }
    )
})
