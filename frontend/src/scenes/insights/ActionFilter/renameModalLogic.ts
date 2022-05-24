import { kea } from 'kea'
import type { renameModalLogicType } from './renameModalLogicType'
import { EntityFilterTypes } from '~/types'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { entityFilterLogic } from 'scenes/insights/ActionFilter/entityFilterLogic'

export interface RenameModalProps {
    filter: EntityFilterTypes
    typeKey: string
}

export const renameModalLogic = kea<renameModalLogicType>({
    props: {} as RenameModalProps,
    key: (props) => props.typeKey,
    path: (key) => ['scenes', 'insights', 'ActionFilter', 'renameModalLogic', key],
    connect: {
        actions: [entityFilterLogic, ['selectFilter']],
    },
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
