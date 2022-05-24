import { kea } from 'kea'
import type { objectTagsLogicType } from './objectTagsLogicType'
import { lemonToast } from '../lemonToast'

export interface ObjectTagsLogicProps {
    id: number
    onChange?: (tag: string, tags: string[]) => void
    tags: string[]
}

function cleanTag(tag?: string): string {
    // Same clean done in posthog/api/tagged_item.py on frontend to mitigate confusion on tag create.
    return (tag ?? '').trim().toLowerCase()
}

export const objectTagsLogic = kea<objectTagsLogicType>({
    path: (key) => ['lib', 'components', 'ObjectTags', 'objectTagsLogic', key],
    props: {} as ObjectTagsLogicProps,
    key: (props) => props.id,
    actions: {
        setTags: (tags: string[]) => ({ tags }),
        setAddingNewTag: (addingNewTag: boolean) => ({ addingNewTag }),
        setNewTag: (newTag: string) => ({ newTag }),
        handleDelete: (tag: string) => ({ tag }),
        handleAdd: true,
    },
    reducers: ({ props }) => ({
        tags: [
            props.tags,
            {
                setTags: (_, { tags }) => tags,
            },
        ],
        addingNewTag: [
            false,
            {
                setAddingNewTag: (_, { addingNewTag }) => addingNewTag,
                setTags: () => false,
            },
        ],
        newTag: [
            '',
            {
                setNewTag: (_, { newTag }) => newTag,
                setTags: () => '',
            },
        ],
        deletedTags: [
            [],
            {
                handleDelete: (state, { tag }) => [...state, tag],
            },
        ],
    }),
    selectors: {
        cleanedNewTag: [(s) => [s.newTag], (newTag) => cleanTag(newTag)],
    },
    listeners: ({ values, props, actions }) => ({
        handleDelete: async ({ tag }) => {
            const newTags = values.tags.filter((_t) => _t !== tag)
            props.onChange?.(tag, newTags)

            // Update local state so that frontend is not blocked by server requests
            actions.setTags(newTags)
        },
        handleAdd: async () => {
            if (values.tags?.includes(values.cleanedNewTag)) {
                lemonToast.error(`Tag "${values.cleanedNewTag}" already is in the list`)
                return
            }
            const newTags = [...(values.tags || []), values.cleanedNewTag]
            props.onChange?.(values.cleanedNewTag, newTags)

            // Update local state so that frontend is not blocked by server requests
            actions.setTags(newTags)
        },
    }),
})
