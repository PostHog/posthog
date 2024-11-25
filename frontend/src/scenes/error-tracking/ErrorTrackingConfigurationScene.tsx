import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonTable, LemonTableColumns, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingSymbolSet } from 'lib/components/Errors/types'
import { JSONViewer } from 'lib/components/JSONViewer'
import { useEffect, useState } from 'react'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'

import {
    errorTrackingConfigurationSceneLogic,
    ErrorTrackingConfigurationTab,
} from './errorTrackingConfigurationSceneLogic'
import { errorTrackingSymbolSetLogic } from './errorTrackingSymbolSetLogic'
import { SymbolSetUploadModal } from './SymbolSetUploadModal'

export const scene: SceneExport = {
    component: ErrorTrackingConfigurationScene,
    logic: errorTrackingConfigurationSceneLogic,
}

export function ErrorTrackingConfigurationScene(): JSX.Element {
    const { activeTab } = useValues(errorTrackingConfigurationSceneLogic)
    const { setActiveTab } = useActions(errorTrackingConfigurationSceneLogic)

    return (
        <LemonTabs
            activeKey={activeTab}
            tabs={[
                {
                    key: ErrorTrackingConfigurationTab.ALERTS,
                    label: 'Alerts',
                    content: <Alerts />,
                },
                {
                    key: ErrorTrackingConfigurationTab.SYMBOL_SETS,
                    label: 'Symbol sets',
                    content: <SymbolSets />,
                },
            ]}
            onChange={setActiveTab}
        />
    )
}

const Alerts = (): JSX.Element => {
    return (
        <LinkedHogFunctions
            type="destination"
            subTemplateId="exception"
            filters={{
                events: [
                    {
                        id: `$exception`,
                        type: 'events',
                    },
                ],
            }}
        />
    )
}

const SymbolSets = (): JSX.Element => {
    const { missingSymbolSets, validSymbolSets } = useValues(errorTrackingSymbolSetLogic)

    return (
        <div className="space-y-4">
            <h2>Symbol sets</h2>
            <p>
                Source maps are required to demangle any minified code in your exception stack traces. PostHog
                automatically retrieves source maps where possible. Cases where it was not possible are listed below.
                Source maps can be uploaded retroactively but changes will only apply to all future exceptions ingested.
            </p>
            {missingSymbolSets.length > 0 && <SymbolSetTable dataSource={missingSymbolSets} pageSize={5} missing />}
            {validSymbolSets.length > 0 && <SymbolSetTable dataSource={validSymbolSets} pageSize={10} />}
            <SymbolSetUploadModal />
        </div>
    )
}

const SymbolSetTable = ({
    dataSource,
    pageSize,
    missing,
}: {
    dataSource: ErrorTrackingSymbolSet[]
    pageSize: number
    missing?: boolean
}): JSX.Element => {
    const { symbolSetsLoading } = useValues(errorTrackingSymbolSetLogic)
    const { deleteSymbolSet } = useActions(errorTrackingSymbolSetLogic)

    const columns: LemonTableColumns<ErrorTrackingSymbolSet> = [
        { title: missing && 'Missing symbol sets', dataIndex: 'ref' },
        {
            dataIndex: 'id',
            render: (_, { id }) => {
                return (
                    <div className="flex justify-end">
                        {!missing && (
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                tooltip="Delete symbol set"
                                icon={<IconTrash />}
                                onClick={() => deleteSymbolSet(id)}
                                className="py-1"
                            />
                        )}
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
