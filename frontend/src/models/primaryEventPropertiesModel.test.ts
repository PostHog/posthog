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
                '/api/projects/:team_id/event_definitions/:id/': (req) => [
                    200,
                    {
                        id: 'def-1',
                        name: 'my_event',
                        primary_property: (req.body as Record<string, any>).primary_property,
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
            .toDispatchActions(['primaryPropertiesLoaded'])
            .toMatchValues({
                primaryProperties: { my_event: 'existing_prop' },
                loadedEventNames: ['my_event'],
            })
    })

    it('optimistically applies the pin and folds it into loaded state when the request succeeds', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPrimaryProperty('my_event', 'chosen_prop')
        })
            .toDispatchActions([
                'setPrimaryProperty',
                logic.actionCreators.applyOptimisticPrimaryProperty('my_event', 'chosen_prop'),
                logic.actionCreators.setLoadedPrimaryProperty('my_event', 'chosen_prop'),
                'clearOptimisticPrimaryProperty',
                'finishSavingPrimaryProperty',
            ])
            .toMatchValues({
                primaryProperties: { my_event: 'chosen_prop' },
                loadedPrimaryProperties: { my_event: 'chosen_prop' },
                optimisticPrimaryProperties: {},
                savingPrimaryPropertyForEvents: [],
            })
    })

    it('reverts the pin when the request fails', async () => {
        useMocks({
            patch: { '/api/projects/:team_id/event_definitions/:id/': () => [403, { detail: 'nope' }] },
        })

        await expectLogic(logic, () => {
            logic.actions.setPrimaryProperty('my_event', 'chosen_prop')
        })
            .toDispatchActions([
                'setPrimaryProperty',
                logic.actionCreators.applyOptimisticPrimaryProperty('my_event', 'chosen_prop'),
                'clearOptimisticPrimaryProperty',
                'finishSavingPrimaryProperty',
            ])
            .toMatchValues({
                primaryProperties: {},
                loadedPrimaryProperties: {},
                optimisticPrimaryProperties: {},
                savingPrimaryPropertyForEvents: [],
            })
    })

    it('does not mark events as loaded when the load request fails, so they can be retried', async () => {
        useMocks({
            get: { '/api/projects/:team_id/event_definitions/primary_properties/': () => [500, {}] },
        })

        await expectLogic(logic, () => {
            logic.actions.loadPrimaryProperties(['flaky_event'])
        })
            .toDispatchActions(['loadPrimaryProperties'])
            .delay(0)

        expect(logic.values.loadedEventNames).toEqual([])
    })

    it('reverts and does not attempt an update when the event definition lookup fails', async () => {
        let updateAttempted = false
        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions/by_name/': () => [404, { detail: 'not found' }],
            },
            patch: {
                '/api/projects/:team_id/event_definitions/:id/': () => {
                    updateAttempted = true
                    return [200, {}]
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.setPrimaryProperty('missing_event', 'some_prop')
        }).toDispatchActions([
            'setPrimaryProperty',
            logic.actionCreators.applyOptimisticPrimaryProperty('missing_event', 'some_prop'),
            'clearOptimisticPrimaryProperty',
            'finishSavingPrimaryProperty',
        ])

        expect(updateAttempted).toBe(false)
        expect(logic.values.primaryProperties).toEqual({})
        expect(logic.values.savingPrimaryPropertyForEvents).toEqual([])
    })

    it('a save completed during an in-flight refresh is not clobbered by the stale refresh result', async () => {
        let releaseLoad: (() => void) | undefined
        const loadGate = new Promise<void>((resolve) => {
            releaseLoad = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions/by_name/': () => [200, { id: 'def-1', name: 'my_event' }],
                '/api/projects/:team_id/event_definitions/primary_properties/': async () => {
                    await loadGate
                    return [200, { primary_properties: {} }]
                },
            },
        })

        logic.actions.loadPrimaryProperties(['my_event'])
        await expectLogic(logic).toDispatchActions(['loadPrimaryProperties'])

        await expectLogic(logic, () => {
            logic.actions.setPrimaryProperty('my_event', 'fresh')
        }).toDispatchActions(['finishSavingPrimaryProperty'])
        expect(logic.values.primaryProperties).toEqual({ my_event: 'fresh' })

        releaseLoad?.()
        await expectLogic(logic).delay(0)

        expect(logic.values.primaryProperties).toEqual({ my_event: 'fresh' })
        expect(logic.values.loadedPrimaryProperties).toEqual({ my_event: 'fresh' })
    })

    it('lets a later server refresh override a pinned value without a stale optimistic shadow', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPrimaryProperty('my_event', 'chosen_prop')
        }).toDispatchActions(['finishSavingPrimaryProperty'])
        expect(logic.values.primaryProperties).toEqual({ my_event: 'chosen_prop' })

        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions/primary_properties/': () => [
                    200,
                    { primary_properties: { my_event: 'changed_elsewhere' } },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadPrimaryProperties(['my_event'])
        }).toDispatchActions(['primaryPropertiesLoaded'])

        expect(logic.values.primaryProperties).toEqual({ my_event: 'changed_elsewhere' })
    })
})
