import { kea } from 'kea'
import { personsModalLogicType } from './personsModalLogicType'

export const personsModalLogic = kea<personsModalLogicType>({
    actions: () => ({
        setSearchTerm: (term: string) => ({ term }),
        setCohortModalVisible: (visible: boolean) => ({ visible }),
    }),
    reducers: () => ({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { term }) => term,
            },
        ],
        cohortModalVisible: [
            false,
            {
                setCohortModalVisible: (_, { visible }) => visible,
            },
        ],
    }),
})
