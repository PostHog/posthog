import { IconRevert, IconTrash, IconUpload } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonDialog, LemonTable, LemonTableColumns, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingSymbolSet } from 'lib/components/Errors/types'
import { JSONViewer } from 'lib/components/JSONViewer'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { useEffect, useState } from 'react'

import { errorTrackingSymbolSetLogic } from './errorTrackingSymbolSetLogic'
import { SymbolSetUploadModal } from './SymbolSetUploadModal'

export function ErrorTrackingSymbolSets(): JSX.Element {
    const { missingSymbolSets, validSymbolSets } = useValues(errorTrackingSymbolSetLogic)
    const { loadSymbolSets } = useActions(errorTrackingSymbolSetLogic)

    useEffect(() => {
        loadSymbolSets()
    }, [loadSymbolSets])

    return (
        <div className="deprecated-space-y-4">
            <p>
                Source maps are required to demangle any minified code in your exception stack traces. PostHog
                automatically retrieves source maps where possible.
            </p>
            <p>
                Cases where it was not possible are listed below. Source maps can be uploaded retroactively but changes
                will only apply to all future exceptions ingested.
            </p>
            {missingSymbolSets.length > 0 && (
                <SymbolSetTable id="missing" dataSource={missingSymbolSets} pageSize={5} missing />
            )}
            {(validSymbolSets.length > 0 || missingSymbolSets.length === 0) && (
                <SymbolSetTable id="valid" dataSource={validSymbolSets} pageSize={10} />
            )}
            <SymbolSetUploadModal />
        </div>
    )
}

const SymbolSetTable = ({
    id,
    dataSource,
    pageSize,
    missing,
}: {
    id: string
    dataSource: ErrorTrackingSymbolSet[]
    pageSize: number
    missing?: boolean
}): JSX.Element => {
    const { symbolSetsLoading } = useValues(errorTrackingSymbolSetLogic)
    const { deleteSymbolSet, setUploadSymbolSetId } = useActions(errorTrackingSymbolSetLogic)

    const columns: LemonTableColumns<ErrorTrackingSymbolSet> = [
        { title: missing && 'Missing symbol sets', dataIndex: 'ref' },
        { title: 'Created At', dataIndex: 'created_at', render: (data) => humanFriendlyDetailedTime(data as string) },
        {
            dataIndex: 'id',
            render: (_, { id }) => {
                return (
                    <div className="flex justify-end deprecated-space-x-1">
                        <LemonButton
                            type={missing ? 'primary' : 'secondary'}
                            size="xsmall"
                            tooltip={missing ? 'Upload symbol set' : 'Replace symbol set'}
                            icon={missing ? <IconUpload /> : <IconRevert />}
                            onClick={() => setUploadSymbolSetId(id)}
                            className="py-1"
                        >
                            {missing && 'Upload'}
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            tooltip="Delete symbol set"
                            icon={<IconTrash />}
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Delete symbol set',
                                    description: 'Are you sure you want to delete this symbol set?',
                                    secondaryButton: {
                                        type: 'secondary',
                                        children: 'Cancel',
                                    },
                                    primaryButton: {
                                        type: 'primary',
                                        onClick: () => deleteSymbolSet(id),
                                        children: 'Delete',
                                    },
                                })
                            }
                            className="py-1"
                        />
                    </div>
                )
            },
        },
    ]

    if (missing) {
        columns.splice(1, 0, { title: 'Failure reason', dataIndex: 'failure_reason' })
    }

    return (
        <LemonTable
            id={id}
            showHeader={missing}
            pagination={{ pageSize }}
            columns={columns}
            loading={symbolSetsLoading}
            dataSource={dataSource}
            expandable={{
                noIndent: true,
                expandedRowRender: function RenderPropertiesTable(symbolSet) {
                    return <SymbolSetStackFrames symbolSet={symbolSet} />
                },
            }}
        />
    )
}

const SymbolSetStackFrames = ({ symbolSet }: { symbolSet: ErrorTrackingSymbolSet }): JSX.Element => {
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const { loadForSymbolSet } = useActions(stackFrameLogic)
    const [activeTab, setActiveTab] = useState<'contents' | 'context'>('contents')

    useEffect(() => {
        loadForSymbolSet(symbolSet.id)
    }, [loadForSymbolSet, symbolSet])

    const frames = Object.values(stackFrameRecords).filter((r) => r.symbol_set_ref == symbolSet.ref)

    return (
        <LemonCollapse
            size="small"
            panels={frames.map(({ id, raw_id, contents, context }) => ({
                key: id,
                header: raw_id,
                className: 'py-0',
                content: (
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={setActiveTab}
                        tabs={[
                            { key: 'contents', label: 'Contents', content: <JSONViewer src={contents} name={null} /> },
                            context && {
                                key: 'context',
                                label: 'Context',
                                content: <JSONViewer src={context} name={null} />,
                            },
                        ]}
                    />
                ),
            }))}
            embedded
        />
    )
}
