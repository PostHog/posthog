import { kea } from 'kea'
import { apiKeyCommandLogicType } from 'types/lib/components/CommandPalette/CustomCommands/apiKeyCommandLogicType'

export const apiKeyCommandLogic = kea<apiKeyCommandLogicType>({
    actions: {
        setLabelInput: (input: string) => ({ input }),
    },
    reducers: {
        labelInput: [
            '',
            {
                setLabelInput: (_, { input }) => input,
            },
        ],
    },
})
