import { kea } from 'kea'
import api from 'lib/api'
import { definitionPanelLogicType } from './definitionPanelLogicType'
import { DefinitionShapeType, DefinitionType } from 'lib/components/DefinitionPanel/types'
import { errorToast } from 'lib/utils'

// Logic for taxonomic-type agnostic panel that contains taxonomy UI
export const definitionPanelLogic = kea<definitionPanelLogicType>({
    path: ['lib', 'components', 'DefinitionPanel', 'definitionPanelLogic'],
    actions: {
        openDrawer: (id: string | number, type: DefinitionType) => ({ id, type }),
        closeDrawer: true,
    },
    reducers: {
        type: [
            null as DefinitionType | null,
            {
                openDrawer: (_, { type }) => type,
                closeDrawer: () => null,
            },
        ],
        visible: [
            false,
            {
                openDrawer: () => true,
                closeDrawer: () => false,
            },
        ],
    },
    selectors: {
        typeToEndpoint: [
            (s) => [s.type],
            (type) => {
                if (type === DefinitionType.Events) {
                    return 'event_definitions'
                }
                if (type === DefinitionType.EventProperties) {
                    return 'property_definitions'
                }
                // TODO: Other definition type API's must be implemented.
                throw new Error('This type of definition is not implemented yet!')
            },
        ],
    },
    loaders: ({ values }) => ({
        definition: [
            null as DefinitionShapeType | null,
            {
                loadDefinition: async (id) => {
                    return await api.get(`api/projects/@current/${values.typeToEndpoint}/${id}`)
                },
                closeDrawer: () => null,
            },
        ],
    }),
    listeners: ({ actions }) => ({
        openDrawer: ({ id }) => {
            if (id) {
                actions.loadDefinition(id)
            }
        },
        loadDefinitionFailure: ({ error }) => {
            errorToast('Error fetching definition', error)
        },
    }),
})
