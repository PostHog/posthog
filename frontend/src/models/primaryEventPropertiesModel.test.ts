import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { primaryEventPropertiesModel } from '~/models/primaryEventPropertiesModel'
import { initKeaTests } from '~/test/init'

describe('the primary event properties model', () => {
    // Safety net for the test that calls silenceKeaLoadersErrors() inline
    afterEach(resumeKeaLoadersErrors)

    let logic: ReturnType<typeof primaryEventPropertiesModel.build>

    const flushPendingLoaders = (): Promise<unknown> => new Promise((resolve) => setTimeout(resolve, 0))

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

    it('keeps both batches when two loads for different events overlap', async () => {
        // Holders raise their own load: each inspector row asks for one event name, while the
        // recording and the seekbar ask for a batch. So overlapping loads are the normal case.
        let releaseFirst: () => void = () => {}
        let releaseSecond: () => void = () => {}
        const firstGate = new Promise<void>((resolve) => {
            releaseFirst = resolve
        })
        const secondGate = new Promise<void>((resolve) => {
            releaseSecond = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions/primary_properties/': async ({ request }) => {
                    if (new URL(request.url).searchParams.getAll('names').includes('first_event')) {
                        await firstGate
                        return [200, { primary_properties: { first_event: 'first_prop' } }]
                    }
                    await secondGate
                    return [200, { primary_properties: { second_event: 'second_prop' } }]
                },
            },
        })

        logic.actions.loadPrimaryProperties({ names: ['first_event'] })
        logic.actions.loadPrimaryProperties({ names: ['second_event'] })

        releaseFirst()
        await flushPendingLoaders()
        releaseSecond()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.primaryProperties).toEqual({ first_event: 'first_prop', second_event: 'second_prop' })
        expect(logic.values.loadedEventNames).toEqual(['first_event', 'second_event'])
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

    it('leaves the loaded map unchanged when the update request fails, and still says so', async () => {
        jest.spyOn(lemonToast, 'error')
        useMocks({
            patch: { '/api/projects/:team_id/event_definitions/:id/': () => [403, { detail: 'nope' }] },
        })
        logic.actions.loadPrimaryPropertiesSuccess({ my_event: 'existing_prop' }, { names: ['my_event'] })

        await expectLogic(logic, () => {
            logic.actions.updatePrimaryProperty({ eventName: 'my_event', propertyKey: 'chosen_prop' })
        })
            .toDispatchActions(['updatePrimaryProperty', 'updatePrimaryPropertySuccess'])
            .toMatchValues({ primaryProperties: { my_event: 'existing_prop' } })

        // The unmount guard sits in this catch block, so a failure while mounted must still report.
        expect(posthog.captureException).toHaveBeenCalled()
        expect(lemonToast.error).toHaveBeenCalled()
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

    describe('unmounting while a request is in flight', () => {
        // This model has no mount of its own, so its last holder can unmount mid-request. A loader
        // that reads values afterwards throws "[KEA] Can not find path", which kea-loaders reports
        // through its onFailure hook. Nothing to report is the whole point of the guard.

        it('reports nothing when the last holder unmounts mid-load', async () => {
            let releaseLoad: () => void = () => {}
            const loadGate = new Promise<void>((resolve) => {
                releaseLoad = resolve
            })
            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/primary_properties/': async () => {
                        await loadGate
                        return [200, { primary_properties: { my_event: 'existing_prop' } }]
                    },
                },
            })

            logic.actions.loadPrimaryProperties({ names: ['my_event'] })
            logic.unmount()
            releaseLoad()
            await flushPendingLoaders()

            expect(posthog.captureException).not.toHaveBeenCalled()
        })

        it('still saves a pin the user asked for when the holder unmounts mid-lookup', async () => {
            let patchAttempted = false
            let releaseLookup: () => void = () => {}
            const lookupGate = new Promise<void>((resolve) => {
                releaseLookup = resolve
            })
            useMocks({
                get: {
                    '/api/projects/:team_id/event_definitions/by_name/': async () => {
                        await lookupGate
                        return [200, { id: 'def-1', name: 'my_event' }]
                    },
                },
                patch: {
                    '/api/projects/:team_id/event_definitions/:id/': () => {
                        patchAttempted = true
                        return [200, { id: 'def-1', name: 'my_event', primary_property: 'chosen_prop' }]
                    },
                },
            })

            logic.actions.updatePrimaryProperty({ eventName: 'my_event', propertyKey: 'chosen_prop' })
            logic.unmount()
            releaseLookup()
            await flushPendingLoaders()

            // Closing the popover must not cancel the write: the click already asked for the pin.
            expect(patchAttempted).toBe(true)
            expect(posthog.captureException).not.toHaveBeenCalled()
        })

        it('reports nothing when the last holder unmounts mid-pin', async () => {
            let releaseUpdate: () => void = () => {}
            const updateGate = new Promise<void>((resolve) => {
                releaseUpdate = resolve
            })
            useMocks({
                patch: {
                    '/api/projects/:team_id/event_definitions/:id/': async () => {
                        await updateGate
                        return [200, { id: 'def-1', name: 'my_event', primary_property: 'chosen_prop' }]
                    },
                },
            })

            logic.actions.updatePrimaryProperty({ eventName: 'my_event', propertyKey: 'chosen_prop' })
            await flushPendingLoaders() // let the definition lookup resolve, so the PATCH is the in-flight call
            logic.unmount()
            releaseUpdate()
            await flushPendingLoaders()

            expect(posthog.captureException).not.toHaveBeenCalled()
        })
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
})
