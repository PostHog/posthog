import { LemonTable } from '@posthog/lemon-ui'
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
    return (
        <div className="">
            <div>
                <div className="pl-4 mt-4">
                    <h3>{tableName}</h3>
                </div>
            </div>
            <div className="flex flex-col gap-1">
                <div
                    ref={(el) => {
                        rowsRefs.current[joinedFields.length] = el
                        rowsRefs.current[joinedFields.length]?.setAttribute('id', 'schema')
                    }}
                    className="pl-4 mt-4"
                >
                    <h4>Schema</h4>
                </div>
                <LemonTable
                    className="bg-[white] rounded-none"
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
                <div className="pl-4 mt-4">
                    <h4>Joined Tables</h4>
                </div>
                <LemonTable
                    className="bg-[white] rounded-none"
                    columns={[
                        {
                            key: 'name',
                            render: (_, { nodeId, table }, idx) => (
                                <div
                                    ref={(el) => {
                                        rowsRefs.current[idx] = el
                                        rowsRefs.current[idx]?.setAttribute('id', nodeId)
                                    }}
                                    className="flex flex-col"
                                >
                                    <span className="font-bold">{nodeId}</span>
                                    <span className="text-muted">{table}</span>
                                </div>
                            ),
                        },
                        {
                            key: 'type',
                            render: (_, { type }) => type,
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
