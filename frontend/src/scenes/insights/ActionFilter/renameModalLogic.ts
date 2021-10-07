import { kea } from 'kea'
import { renameModalLogicType } from './renameModalLogicType'
import { EntityFilterTypes } from '~/types'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { entityFilterLogic } from 'scenes/insights/ActionFilter/entityFilterLogic'

export interface RenameModalProps {
    filter: EntityFilterTypes
    typeKey: string
}

export const renameModalLogic = kea<renameModalLogicType<RenameModalProps>>({
    props: {} as RenameModalProps,
    connect: {
        actions: [entityFilterLogic, ['selectFilter']],
    },
    key: (props) => props.typeKey,
    actions: () => ({
        setName: (name: string) => ({ name }),
    }),
    reducers: ({ props }) => ({
        name: [
            getDisplayNameFromEntityFilter(props.filter) ?? '',
            {
                setName: (_, { name }) => name,
                selectFilter: (_, { filter }) => getDisplayNameFromEntityFilter(filter) ?? '',
            },
        ],
    }),
})
