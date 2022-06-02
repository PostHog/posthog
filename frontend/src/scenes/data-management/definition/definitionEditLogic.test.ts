import { definitionLogic } from 'scenes/data-management/definition/definitionLogic'
import { useMocks } from '~/mocks/jest'
import { mockEventDefinitions, mockEventPropertyDefinition } from '~/test/mocks'
import { initKeaTests } from '~/test/init'
import { definitionEditLogic } from 'scenes/data-management/definition/definitionEditLogic'
import { expectLogic } from 'kea-test-utils'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'

describe('definitionEditLogic', () => {
    let logic: ReturnType<typeof definitionEditLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions/:id': mockEventDefinitions[0],
                '/api/projects/:team/property_definitions/:id': mockEventPropertyDefinition,
                '/api/projects/@current/event_definitions/': {
                    results: mockEventDefinitions,
                    count: mockEventDefinitions.length,
                },
                '/api/projects/@current/property_definitions/': {
                    results: [mockEventPropertyDefinition],
                    count: 1,
                },
            },
            patch: {
                '/api/projects/:team/event_definitions/:id': mockEventDefinitions[0],
                '/api/projects/:team/property_definitions/:id': mockEventPropertyDefinition,
            },
        })
        initKeaTests()
        await expectLogic(definitionLogic({ id: '1' })).toFinishAllListeners()
        eventDefinitionsModel.mount()
        logic = definitionEditLogic({ id: '1', definition: mockEventDefinitions[0] })
        logic.mount()
    })

    it('save definition', async () => {
        await expectLogic(logic, () => {
            logic.actions.saveDefinition({
                ...mockEventDefinitions[0],
                description: 'doesnt matter',
            })
        }).toDispatchActions(['saveDefinition', 'setPageMode', 'setDefinition', 'saveDefinitionSuccess'])
    })
})
