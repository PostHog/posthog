import { LemonButton, LemonTable, LemonTableColumn, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { teamLogic } from 'scenes/teamLogic'

import { DataWarehouseViewLink } from '~/types'

import { viewLinkLogic } from '../viewLinkLogic'
import { ViewLinkModal } from '../ViewLinkModal'
import { dataWarehouseJoinsLogic } from './dataWarehouseJoinsLogic'

export const DataWarehouseJoins = (): JSX.Element => {
    const { currentTeamId } = useValues(teamLogic)
    const { joins, joinsLoading } = useValues(dataWarehouseJoinsLogic)
    const { loadJoins } = useActions(dataWarehouseJoinsLogic)
    const { toggleEditJoinModal } = useActions(viewLinkLogic)

    const columns: LemonTableColumns<DataWarehouseViewLink> = [
        {
            title: 'Description',
            render: (_, join) => {
                return (
                    <span className="row-name">
                        Joining {join.joining_table_name} onto {join.source_table_name}
                    </span>
                )
            },
        },
        {
            title: 'Source Table',
            dataIndex: 'source_table_name',
            sorter: (a, b) => (a.source_table_name || '').localeCompare(b.source_table_name || ''),
        },
        {
            title: 'Joining Table',
            dataIndex: 'joining_table_name',
            sorter: (a, b) => (a.joining_table_name || '').localeCompare(b.joining_table_name || ''),
        },
        {
            title: 'Field Name',
            dataIndex: 'field_name',
        },
        createdByColumn<DataWarehouseViewLink>() as LemonTableColumn<
            DataWarehouseViewLink,
            keyof DataWarehouseViewLink | undefined
        >,
        createdAtColumn<DataWarehouseViewLink>() as LemonTableColumn<
            DataWarehouseViewLink,
            keyof DataWarehouseViewLink | undefined
        >,
        {
            width: 0,
            render: (_, join) => {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton fullWidth onClick={() => void toggleEditJoinModal(join)}>
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    status="danger"
                                    fullWidth
                                    onClick={() => {
                                        void deleteWithUndo({
                                            endpoint: `projects/${currentTeamId}/warehouse_view_link`,
                                            object: {
                                                id: join.id,
                                                name: `${join.field_name} on ${join.source_table_name}`,
                                            },
                                            callback: loadJoins,
                                        })
                                    }}
                                >
                                    Delete
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <>
            <LemonTable
                dataSource={joins}
                columns={columns}
                rowKey="id"
                pagination={{ pageSize: 100 }}
                nouns={['join', 'joins']}
                loading={joinsLoading}
            />
            <ViewLinkModal />
        </>
    )
}
