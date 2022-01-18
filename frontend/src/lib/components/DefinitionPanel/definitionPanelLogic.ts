import { kea } from 'kea'
import api from 'lib/api'
import { definitionPanelLogicType } from './definitionPanelLogicType'
import { DefinitionShapeType } from 'lib/components/DefinitionPanel/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

// Logic for taxonomic-type agnostic panel that contains taxonomy UI
export const definitionPanelLogic = kea<definitionPanelLogicType>({
    path: ['lib', 'components', 'DefinitionPanel', 'definitionPanelLogic'],
    actions: {
        openDrawer: (id: string | number, type: TaxonomicFilterGroupType) => ({ id, type }),
        closeDrawer: true,
    },
    reducers: {
        type: [
            null as TaxonomicFilterGroupType | null,
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
                if (type === TaxonomicFilterGroupType.Events) {
                    return 'event_definitions'
                }
                if (type === TaxonomicFilterGroupType.EventProperties) {
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
                loadDefinition: async ({ id }) => {
                    return await api.get(`api/projects/@current/${values.typeToEndpoint}/${id}`)
                },
                saveDefinition: async ({ id, definition }) => {
                    return await api.update(`api/projects/@current/${values.typeToEndpoint}/${id}`, definition)
                },
                closeDrawer: () => null,
            },
        ],
    }),
    listeners: ({ actions }) => ({
        openDrawer: ({ id }) => {
            if (id) {
                actions.loadDefinition({ id })
            }
        },
    }),
})
