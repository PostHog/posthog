import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { definitionEditLogic } from 'scenes/data-management/definition/definitionEditLogic'
import { definitionLogic } from 'scenes/data-management/definition/definitionLogic'
import { eventDefinitionsTableLogic } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { propertyDefinitionsTableLogic } from 'scenes/data-management/properties/propertyDefinitionsTableLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { mockEventDefinitions, mockEventPropertyDefinition } from '~/test/mocks'

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
        eventDefinitionsTableLogic.mount()
        propertyDefinitionsTableLogic.mount()
        logic = definitionEditLogic({ id: '1', definition: mockEventDefinitions[0] })
        logic.mount()
    })

    it('save definition', async () => {
        router.actions.push(urls.eventDefinition('1'))
        await expectLogic(logic, () => {
            logic.actions.saveDefinition(mockEventDefinitions[0])
        }).toDispatchActionsInAnyOrder([
            'saveDefinition',
            'setDefinition',
            eventDefinitionsTableLogic.actionCreators.setLocalEventDefinition(mockEventDefinitions[0]),
        ])
    })
})
