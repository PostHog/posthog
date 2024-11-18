import { IconUpload } from '@posthog/icons'
import { LemonButton, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { errorTrackingSymbolSetLogic } from './errorTrackingSymbolSetLogic'
import { SymbolSetUploadModal } from './SymbolSetUploadModal'

export const scene: SceneExport = {
    component: ErrorTrackingConfigurationScene,
    logic: errorTrackingSymbolSetLogic,
}

export function ErrorTrackingConfigurationScene(): JSX.Element {
    const { setUploadSymbolSetReference } = useActions(errorTrackingSymbolSetLogic)
    const { missingSymbolSets, missingSymbolSetsLoading } = useValues(errorTrackingSymbolSetLogic)

    return (
        <div>
            <h2>Missing symbol sets</h2>
            <p>
                Source maps are required to demangle any minified code in your exception stack traces. PostHog
                automatically retrieves source maps where possible. Cases where it was not possible are listed below.
                Source maps can be uploaded retroactively but changes will only apply to all future exceptions ingested.
            </p>
            <LemonTable
                showHeader={false}
                columns={[
                    { title: 'Reference', dataIndex: 'ref' },
                    {
                        dataIndex: 'ref',
                        width: 154,
                        render: (ref) => {
                            return (
                                <LemonButton
                                    type="primary"
                                    size="xsmall"
                                    icon={<IconUpload />}
                                    onClick={() => setUploadSymbolSetReference(ref || null)}
                                    className="py-1"
                                >
                                    Upload source map
                                </LemonButton>
                            )
                        },
                    },
                ]}
                loading={missingSymbolSetsLoading}
                dataSource={missingSymbolSets}
            />
            <SymbolSetUploadModal />
        </div>
    )
}
