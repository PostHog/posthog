import { kea } from 'kea'
import { sessionsPlayLogicType } from 'types/scenes/sessions/sessionsPlayLogicType'

export const sessionsPlayLogic = kea<sessionsPlayLogicType>({
    actions: {
        toggleAddingTagShown: () => {},
        setAddingTag: (payload) => ({ payload }),
    },
    reducers: {
        addingTagShown: [
            false,
            {
                toggleAddingTagShown: (state) => !state,
            },
        ],
        addingTag: [
            '',
            {
                setAddingTag: (_, { payload }) => payload,
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        toggleAddingTagShown: () => {
            // Clear text when tag input is dismissed
            if (!values.addingTagShown) {
                actions.setAddingTag('')
            }
        },
    }),
    loaders: ({ values, actions }) => ({
        tags: [
            ['activating', 'watched', 'deleted'] as string[], // TODO: Temp values for testing
            {
                createTag: () => {
                    const newTag = [values.addingTag]
                    actions.toggleAddingTagShown()
                    return values.tags.concat(newTag)
                },
            },
        ],
    }),
})
