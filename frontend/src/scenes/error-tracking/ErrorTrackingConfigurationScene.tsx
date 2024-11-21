import { IconTrash, IconUpload } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ErrorTrackingSymbolSet } from 'lib/components/Errors/types'
import { SceneExport } from 'scenes/sceneTypes'

import { errorTrackingSymbolSetLogic } from './errorTrackingSymbolSetLogic'
import { SymbolSetUploadModal } from './SymbolSetUploadModal'

export const scene: SceneExport = {
    component: ErrorTrackingConfigurationScene,
    logic: errorTrackingSymbolSetLogic,
}

export function ErrorTrackingConfigurationScene(): JSX.Element {
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
    const { setUploadSymbolSetReference, deleteSymbolSet } = useActions(errorTrackingSymbolSetLogic)

    const columns: LemonTableColumns<ErrorTrackingSymbolSet> = [
        { title: missing && 'Missing symbol sets', dataIndex: 'ref' },
        {
            dataIndex: 'id',
            render: (id) => {
                return (
                    <div className="flex justify-end">
                        <LemonButton
                            type={missing ? 'primary' : 'secondary'}
                            size="xsmall"
                            icon={<IconUpload />}
                            onClick={() => setUploadSymbolSetReference(id || null)}
                            className="py-1"
                            tooltip="Upload source map"
                        />
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
        />
    )
}
