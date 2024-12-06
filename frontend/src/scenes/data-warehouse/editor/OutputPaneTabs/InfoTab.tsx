import { useValues } from "kea"


import { infoTabLogic } from './infoTabLogic'
import { LemonTable } from "lib/lemon-ui/LemonTable"


interface InfoTabProps {
    codeEditorKey: string
}

export function InfoTab({ codeEditorKey }: InfoTabProps): JSX.Element {
    const { sourceTableItems } = useValues(infoTabLogic({ codeEditorKey: codeEditorKey }))

    return <div className="flex flex-col flex-1 m-4">
        <h3>Dependencies</h3>
        <LemonTable
            columns={[
                {
                    key: 'Name',
                    title: 'Name',
                    render: (_, { name }) => name,
                },
                {
                    key: 'Type',
                    title: 'Type',
                    render: (_, { type }) => type,
                },
                {
                    key: 'Status',
                    title: 'Status',
                    render: (_, { status }) => status,
                },
                {
                    key: 'Last run at',
                    title: 'Last run at',
                    render: (_, { last_run_at }) => last_run_at,
                },
            ]}
            dataSource={sourceTableItems}
        />
    </div>
}
