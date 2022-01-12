import React from 'react'
import { useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { ActorType } from '~/types'
import { Skeleton } from 'antd'
import { groupsModel } from '~/models/groupsModel'
import UserOutlined from '@ant-design/icons/lib/icons/UserOutlined'
import { capitalizeFirstLetter } from 'lib/utils'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { relatedGroupsLogic } from 'scenes/groups/relatedGroupsLogic'
import { GroupActorHeader } from 'scenes/persons/GroupActorHeader'

interface Props {
    groupTypeIndex: number | null
    id: string
}

export function RelatedGroups({ groupTypeIndex, id }: Props): JSX.Element {
    const { relatedActors, relatedActorsLoading } = useValues(relatedGroupsLogic({ groupTypeIndex, id }))
    const { aggregationLabel } = useValues(groupsModel)

    if (relatedActorsLoading) {
        return <Skeleton paragraph={{ rows: 2 }} active />
    }

    const columns: LemonTableColumns<ActorType> = [
        {
            title: 'Type',
            key: 'type',
            render: function RenderActor(_, actor: ActorType) {
                if (actor.type === 'group') {
                    return <>{capitalizeFirstLetter(aggregationLabel(actor.group_type_index).singular)}</>
                } else {
                    return (
                        <>
                            <UserOutlined /> Person
                        </>
                    )
                }
            },
        },
        {
            title: 'id',
            key: 'id',
            render: function RenderActor(_, actor: ActorType) {
                if (actor.type == 'group') {
                    return <GroupActorHeader actor={actor} />
                } else {
                    return <PersonHeader person={actor} withIcon={false} />
                }
            },
        },
    ]

    return relatedActors.length ? (
        <LemonTable
            dataSource={relatedActors}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 30, hideOnSinglePage: true }}
            embedded
        />
    ) : (
        <i>No related groups found</i>
    )
}
