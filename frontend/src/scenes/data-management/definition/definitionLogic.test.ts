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

const mockPropertyUsage = {
    query_usage_30_day: 12,
    last_queried_at: '2026-04-29T18:00:00Z',
    daily: [],
    top_users: [],
    distinct_users: 1,
    automated_query_usage_30_day: 0,
}

describe('definitionLogic', () => {
    let logic: ReturnType<typeof definitionLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions/:id': mockEventDefinitions[0],
                '/api/projects/:team/property_definitions/:id': mockEventPropertyDefinition,
                '/api/projects/:team/property_definitions/:id/usage/': mockPropertyUsage,
            },
        })
        initKeaTests()
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

    describe('event property definition', () => {
        it('load definition on mount', async () => {
            router.actions.push(urls.propertyDefinition('1'))
            logic = definitionLogic({ id: '1' })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['loadDefinition', 'loadDefinitionSuccess', 'loadPropertyUsageSuccess'])
                .toNotHaveDispatchedActions(['loadMetrics'])
                .toMatchValues({
                    definition: mockEventPropertyDefinition,
                    propertyUsage: mockPropertyUsage,
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
                .toNotHaveDispatchedActions(['loadPropertyUsage'])
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
