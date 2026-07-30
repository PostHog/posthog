import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { AlertState } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { AlertType } from '../types'
import { alertsLogic } from './alertsLogic'

const alert = {
    id: 'alert-1',
    name: 'Checkout conversion dropped',
    calculation_interval: 'daily',
    condition: {},
    config: {},
    enabled: true,
    insight: { id: 1 },
    state: AlertState.NOT_FIRING,
    subscribed_users: [],
    threshold: { configuration: {} },
} as unknown as AlertType

describe('alertsLogic', () => {
    let deleteSpy: jest.SpyInstance
    let listSpy: jest.SpyInstance
    let hogFunctionsListSpy: jest.SpyInstance
    let updateSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        listSpy = jest.spyOn(api.alerts, 'list').mockResolvedValue({ results: [alert], count: 1 })
        hogFunctionsListSpy = jest.spyOn(api.hogFunctions, 'list').mockResolvedValue({ results: [], count: 0 })
    })

    afterEach(() => {
        deleteSpy?.mockRestore()
        listSpy.mockRestore()
        hogFunctionsListSpy.mockRestore()
        updateSpy?.mockRestore()
    })

    it('deletes an alert and reloads the list', async () => {
        deleteSpy = jest.spyOn(api.alerts, 'delete').mockResolvedValue()

        const logic = alertsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.deleteAlert(alert)).toFinishAllListeners()

        expect(deleteSpy).toHaveBeenCalledWith(alert.id)
        expect(listSpy).toHaveBeenCalledTimes(2)

        logic.unmount()
    })

    it('keeps the delete action disabled while deleting', async () => {
        let resolveDelete: () => void = () => {}
        const deletePromise = new Promise<void>((resolve) => {
            resolveDelete = resolve
        })
        deleteSpy = jest.spyOn(api.alerts, 'delete').mockReturnValue(deletePromise)

        const logic = alertsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.deleteAlert(alert)
        expect(logic.values.deletingAlertIds).toEqual(new Set([alert.id]))

        resolveDelete()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ deletingAlertIds: new Set() })
        logic.unmount()
    })

    it('keeps the alert toggle loading and patches the latest alert list', async () => {
        let resolveUpdate: (updatedAlert: AlertType) => void = () => {}
        const updatePromise = new Promise<AlertType>((resolve) => {
            resolveUpdate = resolve
        })
        updateSpy = jest.spyOn(api.alerts, 'update').mockReturnValue(updatePromise)

        const logic = alertsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.toggleAlertEnabled(alert)

        expect(updateSpy).toHaveBeenCalledWith(alert.id, { enabled: false })
        expect(logic.values.togglingAlertIds).toEqual(new Set([alert.id]))

        const alertFromNewerList = { ...alert, id: 'alert-2', name: 'Newer filtered result' }
        logic.actions.loadAlertsSuccess({ results: [alert, alertFromNewerList], count: 2 })

        resolveUpdate({ ...alert, enabled: false })

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                alertsResponse: {
                    results: [{ ...alert, enabled: false }, alertFromNewerList],
                    count: 2,
                },
                togglingAlertIds: new Set(),
            })

        logic.unmount()
    })

    it('counts only enabled destinations for alerts on the current page', async () => {
        hogFunctionsListSpy.mockResolvedValue({
            count: 3,
            results: [
                {
                    id: 'destination-1',
                    enabled: true,
                    filters: { properties: [{ key: 'alert_id', value: alert.id }] },
                },
                {
                    id: 'destination-2',
                    enabled: false,
                    filters: { properties: [{ key: 'alert_id', value: alert.id }] },
                },
                {
                    id: 'destination-for-other-alert',
                    enabled: true,
                    filters: { properties: [{ key: 'alert_id', value: 'other-alert' }] },
                },
            ] as unknown as HogFunctionType[],
        })

        const logic = alertsLogic()
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                alertDestinationCounts: { [alert.id]: 1 },
            })

        logic.unmount()
    })
})
