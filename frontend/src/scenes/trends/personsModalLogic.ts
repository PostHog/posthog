import { kea } from 'kea'
import { personsModalLogicType } from './personsModalLogicType'

export const personsModalLogic = kea<personsModalLogicType>({
    actions: () => ({
        setSearchTerm: (term: string) => ({ term }),
    }),
    reducers: () => ({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { term }) => term,
            },
        ],
    }),
})
