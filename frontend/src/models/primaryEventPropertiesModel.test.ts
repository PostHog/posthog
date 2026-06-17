import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { primaryEventPropertiesModel } from '~/models/primaryEventPropertiesModel'
import { initKeaTests } from '~/test/init'

describe('the primary event properties model', () => {
    let logic: ReturnType<typeof primaryEventPropertiesModel.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions/primary_properties/': () => [
                    200,
                    { primary_properties: { my_event: 'existing_prop' } },
                ],
                '/api/projects/:team_id/event_definitions/by_name/': () => [200, { id: 'def-1', name: 'my_event' }],
            },
            patch: {
                '/api/projects/:team_id/event_definitions/:id/': async ({ request }) => [
                    200,
                    {
                        id: 'def-1',
                        name: 'my_event',
                        primary_property: ((await request.json()) as Record<string, any>).primary_property,
                    },
                ],
            },
        })
        initKeaTests()
        logic = primaryEventPropertiesModel()
        logic.mount()
    })

    it('only loads team overrides for events without a taxonomy default', async () => {
        await expectLogic(logic, () => {
            logic.actions.ensureLoadedForEvents(['my_event', '$pageview'])
        })
            .toDispatchActions(['loadPrimaryPropertiesSuccess'])
            .toMatchValues({
                primaryProperties: { my_event: 'existing_prop' },
                loadedEventNames: ['my_event'],
            })
    })

    it('folds the API response into the loaded map when a pin succeeds', async () => {
        await expectLogic(logic, () => {
            logic.actions.updatePrimaryProperty({ eventName: 'my_event', propertyKey: 'chosen_prop' })
        })
            .toDispatchActions(['updatePrimaryProperty', 'updatePrimaryPropertySuccess'])
            .toMatchValues({ primaryProperties: { my_event: 'chosen_prop' } })
    })

    it('reports loading while a pin update is in flight', async () => {
        logic.actions.updatePrimaryProperty({ eventName: 'my_event', propertyKey: 'chosen_prop' })
        expect(logic.values.primaryPropertiesLoading).toBe(true)

        await expectLogic(logic).toDispatchActions(['updatePrimaryPropertySuccess'])
        expect(logic.values.primaryPropertiesLoading).toBe(false)
    })

    it('removes the entry when unpinned', async () => {
        logic.actions.loadPrimaryPropertiesSuccess({ my_event: 'existing_prop' }, { names: ['my_event'] })

        await expectLogic(logic, () => {
            logic.actions.updatePrimaryProperty({ eventName: 'my_event', propertyKey: null })
        })
            .toDispatchActions(['updatePrimaryPropertySuccess'])
            .toMatchValues({ primaryProperties: {} })
    })

    it('leaves the loaded map unchanged when the update request fails', async () => {
        useMocks({
            patch: { '/api/projects/:team_id/event_definitions/:id/': () => [403, { detail: 'nope' }] },
        })
        logic.actions.loadPrimaryPropertiesSuccess({ my_event: 'existing_prop' }, { names: ['my_event'] })

        await expectLogic(logic, () => {
            logic.actions.updatePrimaryProperty({ eventName: 'my_event', propertyKey: 'chosen_prop' })
        })
            .toDispatchActions(['updatePrimaryProperty', 'updatePrimaryPropertySuccess'])
            .toMatchValues({ primaryProperties: { my_event: 'existing_prop' } })
    })

    it('does not attempt an update when the event definition lookup fails', async () => {
        let updateAttempted = false
        useMocks({
            get: { '/api/projects/:team_id/event_definitions/by_name/': () => [404, { detail: 'not found' }] },
            patch: {
                '/api/projects/:team_id/event_definitions/:id/': () => {
                    updateAttempted = true
                    return [200, {}]
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.updatePrimaryProperty({ eventName: 'missing_event', propertyKey: 'some_prop' })
        })
            .toDispatchActions(['updatePrimaryProperty', 'updatePrimaryPropertySuccess'])
            .toMatchValues({ primaryProperties: {} })

        expect(updateAttempted).toBe(false)
    })

    it('does not mark events as loaded when the load request fails, so they can be retried', async () => {
        useMocks({
            get: { '/api/projects/:team_id/event_definitions/primary_properties/': () => [500, {}] },
        })

        await expectLogic(logic, () => {
            logic.actions.loadPrimaryProperties({ names: ['flaky_event'] })
        }).toDispatchActions(['loadPrimaryPropertiesFailure'])

        expect(logic.values.loadedEventNames).toEqual([])
    })
})
