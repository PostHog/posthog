import { createNewDefinition, definitionLogic } from 'scenes/data-management/definition/definitionLogic'
import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { useMocks } from '~/mocks/jest'
import { mockEventDefinitions, mockEventPropertyDefinition } from '~/test/mocks'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

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
            router.actions.push(urls.eventPropertyDefinition('1'))
            logic = definitionLogic({ id: '1' })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadDefinition', 'loadDefinitionSuccess']).toMatchValues({
                definition: mockEventPropertyDefinition,
            })
        })

        it('load new definition on mount', async () => {
            router.actions.push(urls.eventPropertyDefinition('new'))
            logic = definitionLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic)
                .toDispatchActions(['setDefinition', 'setDefinitionSuccess'])
                .toNotHaveDispatchedActions(['loadDefinition'])
                .toMatchValues({
                    definition: createNewDefinition(false),
                })
        })
    })
})
