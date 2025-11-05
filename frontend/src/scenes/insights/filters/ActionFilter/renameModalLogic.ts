import { actions, connect, kea, key, path, props, reducers } from 'kea'

import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

import { EntityFilterTypes } from '~/types'

import type { renameModalLogicType } from './renameModalLogicType'

export interface RenameModalProps {
    filter: EntityFilterTypes
    typeKey: string
}

export const renameModalLogic = kea<renameModalLogicType>([
    props({} as RenameModalProps),
    key((props) => props.typeKey),
    path((key) => ['scenes', 'insights', 'ActionFilter', 'renameModalLogic', key]),
    connect((props: RenameModalProps) => ({
        actions: [entityFilterLogic({ typeKey: props.typeKey }), ['selectFilter']],
    })),
    actions(() => ({
        setName: (name: string) => ({ name }),
    })),
    reducers(({ props }) => ({
        name: [
            getDisplayNameFromEntityFilter(props.filter) ?? '',
            {
                setName: (_, { name }) => name,
                selectFilter: (_, { filter }) => getDisplayNameFromEntityFilter(filter) ?? '',
            },
        ],
    })),
])
