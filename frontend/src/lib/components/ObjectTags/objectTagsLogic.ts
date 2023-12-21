import equal from 'fast-deep-equal'
import { actions, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { objectTagsLogicType } from './objectTagsLogicType'

export interface ObjectTagsLogicProps {
    id: number
    onChange?: (tag: string, tags: string[]) => void
    tags: string[]
}

function cleanTag(tag?: string): string {
    // Same clean done in posthog/api/tagged_item.py on frontend to mitigate confusion on tag create.
    return (tag ?? '').trim().toLowerCase()
}

export const objectTagsLogic = kea<objectTagsLogicType>([
    path(['lib', 'components', 'ObjectTags', 'objectTagsLogic']),
    props({} as ObjectTagsLogicProps),
    key((props) => props.id),
    actions({
        setTags: (tags: string[]) => ({ tags }),
        setAddingNewTag: (addingNewTag: boolean) => ({ addingNewTag }),
        setNewTag: (newTag: string) => ({ newTag }),
        handleDelete: (tag: string) => ({ tag }),
        handleAdd: (addedTag: string) => ({ addedTag }),
    }),
    reducers(({ props }) => ({
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
    })),
    selectors({
        cleanedNewTag: [(s) => [s.newTag], (newTag) => cleanTag(newTag)],
    }),
    listeners(({ values, props, actions }) => ({
        handleDelete: async ({ tag }) => {
            const newTags = values.tags.filter((_t) => _t !== tag)
            props.onChange?.(tag, newTags)

            // Update local state so that frontend is not blocked by server requests
            actions.setTags(newTags)
        },
        handleAdd: async ({ addedTag }) => {
            const cleanedAddedTag = cleanTag(addedTag)
            if (values.tags?.includes(cleanedAddedTag)) {
                lemonToast.error(`Tag "${cleanedAddedTag}" already is in the list`)
                return
            }
            const newTags = [...(values.tags || []), cleanedAddedTag]
            props.onChange?.(cleanedAddedTag, newTags)

            // Update local state so that frontend is not blocked by server requests
            actions.setTags(newTags)
        },
    })),
    propsChanged(({ actions, props }, oldProps) => {
        if (!equal(props.tags, oldProps.tags)) {
            actions.setTags(props.tags)
        }
    }),
])
