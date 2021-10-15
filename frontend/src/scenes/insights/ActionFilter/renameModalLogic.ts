import { kea } from 'kea'
import { renameModalLogicType } from './renameModalLogicType'
import { EntityFilterTypes } from '~/types'
import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { entityFilterLogic } from 'scenes/insights/ActionFilter/entityFilterLogic'
import { getProjectBasedLogicKeyBuilder, ProjectBasedLogicProps } from '../../../lib/utils/logics'

export interface RenameModalProps extends ProjectBasedLogicProps {
    filter: EntityFilterTypes
    typeKey: string
}

export const renameModalLogic = kea<renameModalLogicType<RenameModalProps>>({
    props: {} as RenameModalProps,
    key: getProjectBasedLogicKeyBuilder((props) => props.typeKey),
    connect: (props: RenameModalProps) => ({
        actions: [
            entityFilterLogic({ teamId: props.teamId, typeKey: props.typeKey, filters: {}, setFilters: () => {} }),
            ['selectFilter'],
        ],
    }),
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
