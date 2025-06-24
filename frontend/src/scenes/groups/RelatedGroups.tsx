import { IconPerson } from '@posthog/icons'
import { useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { capitalizeFirstLetter } from 'lib/utils'
import { relatedGroupsLogic } from 'scenes/groups/relatedGroupsLogic'
import { GroupActorDisplay } from 'scenes/persons/GroupActorDisplay'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { groupsModel } from '~/models/groupsModel'
import { ActorType } from '~/types'

interface Props {
    groupTypeIndex: number | null
    id: string
    type?: 'person' | 'group'
    limit?: number
}

export function RelatedGroups({ groupTypeIndex, id, type, limit }: Props): JSX.Element {
    const { relatedActors, relatedActorsLoading } = useValues(relatedGroupsLogic({ groupTypeIndex, id, type, limit }))
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

    return (
        <LemonTable
            dataSource={relatedActors}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 30, hideOnSinglePage: true }}
            loading={relatedActorsLoading}
            nouns={['related group', 'related groups']}
            emptyState="No related groups found"
        />
    )
}
