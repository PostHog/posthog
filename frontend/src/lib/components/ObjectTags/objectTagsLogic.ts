import { actions, kea, key, listeners, path, props, reducers } from 'kea'

import { uniqueBy } from 'lib/utils'

import type { objectTagsLogicType } from './objectTagsLogicType'

export interface ObjectTagsLogicProps {
    id: number
    onChange?: (tags: string[]) => void
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
        setEditingTags: (editingTags: boolean) => ({ editingTags }),
    }),
    reducers(() => ({
        editingTags: [
            false,
            {
                setEditingTags: (_, { editingTags }) => editingTags,
            },
        ],
    })),
    listeners(({ props }) => ({
        setTags: ({ tags }) => {
            const nextTags = uniqueBy(tags.map(cleanTag), (i) => i)
            props.onChange?.(nextTags)
        },
    })),
])
