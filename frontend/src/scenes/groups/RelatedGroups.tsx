import { useValues } from 'kea'

import { IconPerson } from '@posthog/icons'

import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { capitalizeFirstLetter } from 'lib/utils'
import { relatedGroupsLogic } from 'scenes/groups/relatedGroupsLogic'
import { GroupActorDisplay } from 'scenes/persons/GroupActorDisplay'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { groupsModel } from '~/models/groupsModel'
import { ActorType } from '~/types'

export interface RelatedGroupsProps {
    groupTypeIndex: number | null
    id: string
    type?: 'person' | 'group'
    pageSize?: number
    embedded?: boolean
}

export function RelatedGroups({
    groupTypeIndex,
    id,
    type,
    pageSize,
    embedded = false,
}: RelatedGroupsProps): JSX.Element {
    const { relatedActors, relatedPeople, relatedActorsLoading } = useValues(
        relatedGroupsLogic({ groupTypeIndex, id, type })
    )
    const dataSource = type === 'person' ? relatedPeople : relatedActors
    const { aggregationLabel } = useValues(groupsModel)

    const columns: LemonTableColumns<ActorType> = [
        {
            title: 'Type',
            key: 'type',
            render: function RenderActor(_, actor: ActorType) {
                if (actor.type === 'group') {
                    return <>{capitalizeFirstLetter(aggregationLabel(actor.group_type_index).singular)}</>
                }
                return (
                    <>
                        <IconPerson /> Person
                    </>
                )
            },
        },
        {
            title: 'id',
            key: 'id',
            render: function RenderActor(_, actor: ActorType) {
                if (actor.type === 'group') {
                    return <GroupActorDisplay actor={actor} />
                }
                return <PersonDisplay person={actor} withIcon={false} />
            },
        },
    ]

    const nouns: [string, string] =
        type === 'person' ? ['related person', 'related people'] : ['related group', 'related groups']

    return (
        <LemonTable
            dataSource={dataSource}
            columns={columns}
            embedded={embedded}
            rowKey="id"
            pagination={{ pageSize: pageSize || 30, hideOnSinglePage: true }}
            loading={relatedActorsLoading}
            nouns={nouns}
            emptyState="No related groups found"
        />
    )
}
