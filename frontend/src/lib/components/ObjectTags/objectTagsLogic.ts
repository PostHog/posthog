import { kea } from 'kea'
import { objectTagsLogicType } from './objectTagsLogicType'
import { errorToast } from 'lib/utils'

interface ObjectTagsLogicProps {
    id?: string
    onChange?: (tag: string, tags: string[], id?: string) => void
    tags: string[]
}

function cleanTag(tag?: string): string {
    // Same clean done in posthog/api/tagged_item.py on frontend to mitigate confusion on tag create.
    return (tag ?? '').trim().toLowerCase()
}

export const objectTagsLogic = kea<objectTagsLogicType<ObjectTagsLogicProps>>({
    path: (key) => ['lib', 'components', 'ObjectTags', 'objectTagsLogic', key],
    props: {} as ObjectTagsLogicProps,
    key: (props) => props?.id || 'tags',
    actions: {
        setTags: (tags: string[]) => ({ tags }),
        setAddingNewTag: (addingNewTag: boolean) => ({ addingNewTag }),
        setNewTag: (newTag: string) => ({ newTag }),
        handleDelete: (tag: string) => ({ tag }),
        handleAdd: (tag: string) => ({ tag }),
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
            },
        ],
        newTag: [
            '',
            {
                setNewTag: (_, { newTag }) => newTag,
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
        handleDelete: async ({ tag }, breakpoint) => {
            // Universal breakpoint since object tags can be used async or sync
            const newTags = values.tags.filter((_t) => _t !== tag)
            props.onChange?.(tag, newTags, props.id)
            actions.setTags(newTags) // Update local state
            breakpoint()
        },
        handleAdd: async (_, breakpoint) => {
            // Universal breakpoint since object tags can be used async or sync
            if (values.tags?.includes(values.cleanedNewTag)) {
                errorToast("Oops! Can't add that tag", 'That tag already exists.', 'Validation error')
                return
            }
            const newTags = [...(values.tags || []), values.cleanedNewTag]
            props.onChange?.(values.cleanedNewTag, newTags, props.id)
            actions.setTags(newTags) // Update local state
            actions.setNewTag('')
            actions.setAddingNewTag(false)
            breakpoint()
        },
    }),
})
