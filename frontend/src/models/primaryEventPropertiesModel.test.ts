import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { primaryEventPropertiesModel } from '~/models/primaryEventPropertiesModel'
import { initKeaTests } from '~/test/init'

describe('the primary event properties model', () => {
    // Safety net for the test that calls silenceKeaLoadersErrors() inline
    afterEach(resumeKeaLoadersErrors)

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

    it('keeps the results of both loads when an earlier load finishes after a later one', async () => {
        let releaseFirstLoad: () => void = () => {}
        const firstLoadGate = new Promise<void>((resolve) => {
            releaseFirstLoad = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions/primary_properties/': async ({ request }) => {
                    if (request.url.includes('first_event')) {
                        await firstLoadGate
                        return [200, { primary_properties: { first_event: 'first_prop' } }]
                    }
                    return [200, { primary_properties: { second_event: 'second_prop' } }]
                },
            },
        })

        const firstLoad = logic.asyncActions.loadPrimaryProperties({ names: ['first_event'] })
        await logic.asyncActions.loadPrimaryProperties({ names: ['second_event'] })
        releaseFirstLoad()
        await firstLoad

        expect(logic.values.primaryProperties).toEqual({ first_event: 'first_prop', second_event: 'second_prop' })
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
        expect(logic.values.primaryPropertyChangesLoading).toBe(true)

        await expectLogic(logic).toDispatchActions(['updatePrimaryPropertySuccess'])
        expect(logic.values.primaryPropertyChangesLoading).toBe(false)
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
        // Deliberate loader failure — kea-loaders would log it
        silenceKeaLoadersErrors()
        useMocks({
            get: { '/api/projects/:team_id/event_definitions/primary_properties/': () => [500, {}] },
        })

        await expectLogic(logic, () => {
            logic.actions.loadPrimaryProperties({ names: ['flaky_event'] })
        }).toDispatchActions(['loadPrimaryPropertiesFailure'])

        expect(logic.values.loadedEventNames).toEqual([])
    })

    it.each([
        {
            name: 'a load',
            method: 'get',
            url: '/api/projects/:team_id/event_definitions/primary_properties/',
            start: (): Promise<unknown> => logic.asyncActions.loadPrimaryProperties({ names: ['my_event'] }),
        },
        {
            name: 'a pin',
            method: 'patch',
            url: '/api/projects/:team_id/event_definitions/:id/',
            start: (): Promise<unknown> =>
                logic.asyncActions.updatePrimaryProperty({ eventName: 'my_event', propertyKey: 'chosen_prop' }),
        },
    ])('does not report an error when the model unmounts during $name', async ({ method, url, start }) => {
        let releaseResponse: () => void = () => {}
        const responseGate = new Promise<void>((resolve) => {
            releaseResponse = resolve
        })
        useMocks({
            [method]: {
                [url]: async () => {
                    await responseGate
                    return [200, { id: 'def-1', primary_property: 'chosen_prop', primary_properties: {} }]
                },
            },
        })
        const loaderSettled = start()
        logic.unmount()
        releaseResponse()
        await loaderSettled

        expect(posthog.captureException).not.toHaveBeenCalled()
    })
})
