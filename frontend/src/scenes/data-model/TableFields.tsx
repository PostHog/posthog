import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'

import { viewLinkLogic } from 'scenes/data-warehouse/viewLinkLogic'

export interface FixedField {
    column: string
    type: string
}

export interface JoinedField {
    nodeId: string
    type: string
    table: string
}

export interface TableFieldsProps {
    fixedFields: FixedField[]
    joinedFields: JoinedField[]
    rowsRefs: React.MutableRefObject<(HTMLDivElement | null)[]>
    tableName: string
}

export function TableFields({ fixedFields, joinedFields, rowsRefs, tableName }: TableFieldsProps): JSX.Element {
    const { toggleJoinTableModal, selectSourceTable } = useActions(viewLinkLogic)

    return (
        <div className="">
            <div>
                <div className="pl-4 mt-4">
                    <h3>{tableName}</h3>
                </div>
            </div>
            <div className="flex flex-col gap-1">
                <div className="pl-4 mt-4">
                    <h4>Schema</h4>
                </div>
                <LemonTable
                    className="bg-primary rounded-none"
                    columns={[
                        {
                            key: 'column',
                            render: (_, { column }) => column,
                        },
                        {
                            key: 'type',
                            render: (_, { type }) => type,
                        },
                    ]}
                    dataSource={fixedFields}
                    loading={false}
                    showHeader={false}
                />
            </div>
            <div>
                <div className="px-4 my-4 flex flex-row justify-between">
                    <h4>Joined Tables</h4>
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        icon={<IconPlus />}
                        onClick={() => {
                            selectSourceTable(tableName)
                            toggleJoinTableModal()
                        }}
                    >
                        Add join
                    </LemonButton>
                </div>
                <LemonTable
                    className="bg-primary rounded-none"
                    columns={[
                        {
                            key: 'name',
                            render: (_, { nodeId }, idx) => (
                                <div
                                    ref={(el) => {
                                        rowsRefs.current[idx] = el
                                        rowsRefs.current[idx]?.setAttribute('id', `${nodeId}_joined`)
                                    }}
                                    className="flex flex-col"
                                >
                                    <span className="font-bold">{nodeId}</span>
                                </div>
                            ),
                        },
                    ]}
                    loading={false}
                    showHeader={false}
                    dataSource={joinedFields}
                />
            </div>
        </div>
    )
}
