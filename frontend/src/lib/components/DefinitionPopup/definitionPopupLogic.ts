import { kea } from 'kea'
import { definitionPopupLogicType } from './definitionPopupLogicType'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
export enum DefinitionPopupState {
    Edit = 'edit',
    View = 'view',
}

interface DefinitionPopupLogicProps {
    type: TaxonomicFilterGroupType
}

export const definitionPopupLogic = kea<definitionPopupLogicType<DefinitionPopupLogicProps, DefinitionPopupState>>({
    props: {} as DefinitionPopupLogicProps,
    path: ['lib', 'components', 'DefinitionPanel', 'definitionPopupLogic'],
    actions: {
        setPopupState: (state: DefinitionPopupState) => ({ state }),
    },
    reducers: {
        state: [
            DefinitionPopupState.View as DefinitionPopupState,
            {
                setPopupState: (_, { state }) => state,
            },
        ],
    },
    selectors: {
        type: [() => [(_, props) => props.type], (type) => type],
    },
})
