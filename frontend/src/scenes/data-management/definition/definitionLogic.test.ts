import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import {
    createNewDefinition,
    decodeDefinitionId,
    definitionLogic,
} from 'scenes/data-management/definition/definitionLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockEventPropertyDefinition } from '~/test/mocks'

describe('definitionLogic', () => {
    let logic: ReturnType<typeof definitionLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions/:id': mockEventDefinitions[0],
                '/api/projects/:team/property_definitions/:id': mockEventPropertyDefinition,
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('event definition', () => {
        it('load definition on mount', async () => {
            router.actions.push(urls.eventDefinition('1'))
            logic = definitionLogic({ id: '1' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadDefinition', 'loadDefinitionSuccess']).toMatchValues({
                definition: mockEventDefinitions[0],
            })
        })

        it('load new definition on mount', async () => {
            router.actions.push(urls.eventDefinition('new'))
            logic = definitionLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['setDefinition', 'setDefinitionSuccess'])
                .toNotHaveDispatchedActions(['loadDefinition'])
                .toMatchValues({
                    definition: createNewDefinition(true),
                })
        })
    })

    describe('event definition not-found handling', () => {
        it('marks definition missing on a 404 but not on a server error', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions/404id': () => [404, { detail: 'Not found' }],
                    '/api/projects/:team/event_definitions/500id': () => [500, { detail: 'Server error' }],
                    '/api/projects/:team/event_definitions/:id/metrics': { query_usage_30_day: 0 },
                },
            })

            router.actions.push(urls.eventDefinition('404id'))
            logic = definitionLogic({ id: '404id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadDefinition', 'loadDefinitionFailure']).toMatchValues({
                definitionMissing: true,
            })
            logic.unmount()

            router.actions.push(urls.eventDefinition('500id'))
            logic = definitionLogic({ id: '500id' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadDefinition', 'loadDefinitionFailure']).toMatchValues({
                definitionMissing: false,
            })
        })

        it('degrades to no metrics instead of failing when the metrics fetch errors', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions/:id': mockEventDefinitions[0],
                    '/api/projects/:team/event_definitions/:id/metrics': () => [500, { detail: 'Server error' }],
                },
            })

            router.actions.push(urls.eventDefinition('1'))
            logic = definitionLogic({ id: '1' })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['loadMetrics', 'loadMetricsSuccess'])
                .toNotHaveDispatchedActions(['loadMetricsFailure'])
                .toMatchValues({ metrics: null })
        })
    })

    describe('event property definition', () => {
        it('load definition on mount', async () => {
            router.actions.push(urls.propertyDefinition('1'))
            logic = definitionLogic({ id: '1' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadDefinition', 'loadDefinitionSuccess']).toMatchValues({
                definition: mockEventPropertyDefinition,
            })
        })

        it('load new definition on mount', async () => {
            router.actions.push(urls.propertyDefinition('new'))
            logic = definitionLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['setDefinition', 'setDefinitionSuccess'])
                .toNotHaveDispatchedActions(['loadDefinition'])
                .toMatchValues({
                    definition: createNewDefinition(false),
                })
        })

        it('decodes route ids without throwing on malformed percent sequences', () => {
            expect(decodeDefinitionId('%24builtin_%24virt_bot_name')).toBe('$builtin_$virt_bot_name')
            expect(decodeDefinitionId('100%off')).toBe('100%off')
            expect(decodeDefinitionId(undefined)).toBeUndefined()
        })

        it('resolves virtual property definitions from the taxonomy instead of the API', async () => {
            router.actions.push(urls.propertyDefinition('$builtin_$virt_bot_name'))
            logic = definitionLogic({ id: '$builtin_$virt_bot_name' })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['loadDefinition', 'loadDefinitionSuccess'])
                .toMatchValues({
                    definition: expect.objectContaining({
                        id: '$builtin_$virt_bot_name',
                        name: '$virt_bot_name',
                        virtual: true,
                    }),
                    definitionMissing: false,
                })
        })
    })
})
