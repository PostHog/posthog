import { LemonTable } from '@posthog/lemon-ui'

const FAKE_DATA = [
    { column: 'id', type: 'integer' },
    { column: 'name', type: 'string' },
    { column: 'email', type: 'string' },
    { column: 'created_at', type: 'datetime' },
    { column: 'is_active', type: 'boolean' },
    { column: 'properties', type: 'json' },
]

interface TableFieldsProps {
    joinedData: { name: string; type: string; table: string }[]
    rowsRefs: React.MutableRefObject<(HTMLDivElement | null)[]>
}

export function TableFields({ joinedData, rowsRefs }: TableFieldsProps): JSX.Element {
    return (
        <div className="">
            <div>
                <div className="pl-4 mt-4">
                    <h3>person</h3>
                </div>
            </div>
            <div className="flex flex-col gap-1">
                <div
                    ref={(el) => {
                        rowsRefs.current[joinedData.length] = el
                        rowsRefs.current[joinedData.length]?.setAttribute('id', 'schema')
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
                    dataSource={FAKE_DATA}
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
                            render: (_, { name, table }, idx) => (
                                <div
                                    ref={(el) => {
                                        rowsRefs.current[idx] = el
                                        rowsRefs.current[idx]?.setAttribute('id', name)
                                    }}
                                    className="flex flex-col"
                                >
                                    <span className="font-bold">{name}</span>
                                    <span className="text-muted">{table}</span>
                                </div>
                            ),
                        },
                        {
                            key: 'type',
                            render: (_, { type }) => type,
                        },
                    ]}
                    dataSource={joinedData}
                    loading={false}
                    showHeader={false}
                />
            </div>
        </div>
    )
}
