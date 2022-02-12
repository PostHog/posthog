import { kea } from 'kea'
import { objectTagsLogicType } from './objectTagsLogicType'
import { errorToast } from 'lib/utils'

interface ObjectTagsLogicProps {
    id?: string
    onChange?: (tag: string, tags: string[], id?: string) => void
    tags: string[]
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
    listeners: ({ values, props, actions }) => ({
        handleDelete: async ({ tag }, breakpoint) => {
            // Universal breakpoint since object tags can be used async or sync
            await breakpoint(100)
            props.onChange?.(
                tag,
                values.tags.filter((_t) => _t !== tag),
                props.id
            )
        },
        handleAdd: async ({ tag }, breakpoint) => {
            // Universal breakpoint since object tags can be used async or sync
            await breakpoint(100)

            if (props.tags?.includes(tag)) {
                errorToast("Oops! Can't add that tag", 'That tag already exists.')
                return
            }
            props.onChange?.(tag, [...(values.tags || []), tag], props.id)
            actions.setNewTag('')
            actions.setAddingNewTag(false)
        },
    }),
})
