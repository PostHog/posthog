import React from 'react'
import { useValues } from 'kea'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { RelatedActor } from '~/types'
import { Skeleton } from 'antd'
import { groupsModel } from '~/models/groupsModel'
import UserOutlined from '@ant-design/icons/lib/icons/UserOutlined'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'
import { Link } from 'lib/components/Link'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { relatedGroupsLogic } from 'scenes/groups/relatedGroupsLogic'

interface Props {
    groupTypeIndex: number | null
    id: string
}

export function RelatedGroups({ groupTypeIndex, id }: Props): JSX.Element {
    const { relatedActors, relatedActorsLoading } = useValues(relatedGroupsLogic({ groupTypeIndex, id }))
    const { groupTypes } = useValues(groupsModel)

    if (relatedActorsLoading) {
        return <Skeleton paragraph={{ rows: 2 }} active />
    }

    const columns: LemonTableColumns<RelatedActor> = [
        {
            title: 'Type',
            key: 'type',
            render: function RenderCount(_, actor: RelatedActor) {
                if (actor.type === 'group') {
                    return <>{capitalizeFirstLetter(groupTypes[actor.group_type_index]?.group_type ?? '')}</>
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
            render: function RenderCount(_, actor: RelatedActor) {
                let url: string
                if (actor.type == 'group') {
                    url = urls.group(actor.group_type_index, actor.id)
                    return (
                        <Link to={url} data-attr="related-group-link">
                            {actor.id}
                        </Link>
                    )
                } else {
                    url = urls.person(actor.person.distinct_ids[0])
                    return (
                        <Link to={url} data-attr="related-person-link">
                            {asDisplay(actor.person)}
                        </Link>
                    )
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
