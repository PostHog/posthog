import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { definitionLogic } from '../definition/definitionLogic'
import { schemaManagementLogic } from '../schema/schemaManagementLogic'
import { eventDefinitionSchemaLogic } from './eventDefinitionSchemaLogic'

describe('eventDefinitionSchemaLogic', () => {
    let logic: ReturnType<typeof eventDefinitionSchemaLogic.build>
    let schemaLogic: ReturnType<typeof schemaManagementLogic.build>
    let defLogic: ReturnType<typeof definitionLogic.build>

    beforeEach(() => {
        initKeaTests()

        useMocks({
            get: {
                '/api/projects/:teamId/event_definitions/:id': {
                    id: 'event-def-1',
                    name: 'test_event',
                    enforcement_mode: 'allow',
                },
                '/api/projects/:teamId/event_schemas': {
                    results: [
                        {
                            id: 'schema-1',
                            event_definition: 'event-def-1',
                            property_group_id: 'group-1',
                            property_group: {
                                id: 'group-1',
                                name: 'Test Group',
                                properties: [{ id: 'prop-1', name: 'prop1', property_type: 'String' }],
                            },
                        },
                    ],
                },
                '/api/projects/:teamId/schema_property_groups/': {
                    results: [
                        {
                            id: 'group-1',
                            name: 'Test Group',
                            properties: [{ id: 'prop-1', name: 'prop1', property_type: 'String' }],
                        },
                    ],
                },
            },
            patch: {
                '/api/projects/:teamId/schema_property_groups/:id/': () => [
                    200,
                    {
                        id: 'group-1',
                        name: 'Updated Group',
                        properties: [{ id: 'prop-1', name: 'updatedProp', property_type: 'Numeric' }],
                    },
                ],
            },
            post: {
                '/api/projects/:teamId/schema_property_groups/': () => [
                    200,
                    {
                        id: 'group-2',
                        name: 'New Group',
                        properties: [],
                    },
                ],
            },
        })

        // definitionLogic must be mounted first since eventDefinitionSchemaLogic connects to it
        defLogic = definitionLogic({ id: 'event-def-1' })
        schemaLogic = schemaManagementLogic({ key: 'event-event-def-1' })
        logic = eventDefinitionSchemaLogic({
            eventDefinitionId: 'event-def-1',
        })
    })

    it('should reload event schemas when property group is updated', () => {
        defLogic.mount()
        schemaLogic.mount()
        logic.mount()

        const loadEventSchemasSpy = jest.spyOn(logic.actions, 'loadEventSchemas')

        const mockPropertyGroups = [
            {
                id: 'group-1',
                name: 'Updated Group',
                properties: [
                    {
                        id: 'prop-1',
                        name: 'updatedProp',
                        property_type: 'Numeric',
                        is_required: false,
                        description: '',
                        order: 0,
                    },
                ],
            },
        ]

        schemaLogic.actions.updatePropertyGroupSuccess(mockPropertyGroups)

        expect(loadEventSchemasSpy).toHaveBeenCalled()
    })

    it('should reload event schemas when a new property group is created', () => {
        defLogic.mount()
        schemaLogic.mount()
        logic.mount()

        const loadEventSchemasSpy = jest.spyOn(logic.actions, 'loadEventSchemas')

        const mockNewPropertyGroup = [
            {
                id: 'group-2',
                name: 'New Group',
                properties: [],
            },
        ]

        schemaLogic.actions.createPropertyGroupSuccess(mockNewPropertyGroup)

        expect(loadEventSchemasSpy).toHaveBeenCalled()
    })
})
