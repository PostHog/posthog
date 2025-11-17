import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { schemaManagementLogic } from '../schema/schemaManagementLogic'
import { eventDefinitionSchemaLogic } from './eventDefinitionSchemaLogic'

describe('eventDefinitionSchemaLogic', () => {
    let logic: ReturnType<typeof eventDefinitionSchemaLogic.build>
    let schemaLogic: ReturnType<typeof schemaManagementLogic.build>

    beforeEach(() => {
        initKeaTests()

        useMocks({
            get: {
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

        // Build the logic instances with the same key
        schemaLogic = schemaManagementLogic({ key: 'event-event-def-1' })
        logic = eventDefinitionSchemaLogic({ eventDefinitionId: 'event-def-1' })
    })

    it('should reload event schemas when property group is updated', () => {
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
