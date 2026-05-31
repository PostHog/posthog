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
            .toDispatchActions(['loadPrimaryPropertiesSuccess'])
            .toMatchValues({
                primaryProperties: { my_event: 'existing_prop' },
                loadedEventNames: ['my_event'],
            })
    })

    it('optimistically applies the pin and keeps it when the request succeeds', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPrimaryProperty('my_event', 'chosen_prop')
        })
            .toDispatchActions([
                'setPrimaryProperty',
                logic.actionCreators.applyOptimisticPrimaryProperty('my_event', 'chosen_prop'),
                'finishSavingPrimaryProperty',
            ])
            .toMatchValues({
                primaryProperties: { my_event: 'chosen_prop' },
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
                logic.actionCreators.applyOptimisticPrimaryProperty('my_event', null),
                'finishSavingPrimaryProperty',
            ])
            .toMatchValues({
                primaryProperties: {},
                savingPrimaryPropertyForEvents: [],
            })
    })
})
