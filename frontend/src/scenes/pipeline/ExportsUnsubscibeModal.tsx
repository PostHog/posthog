import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'

import { exportsUnsubscribeModalLogic } from './exportsUnsubscibeModalLogic'
import { RenderApp } from './utils'

export function ExportsUnsubscribeModal(): JSX.Element {
    const { modalOpen, unsubscribeDisabled, loading, pluginConfigs, plugins } = useValues(exportsUnsubscribeModalLogic)
    const { closeModal } = useActions(exportsUnsubscribeModalLogic)

    return (
        <LemonModal
            onClose={closeModal}
            isOpen={modalOpen}
            width={600}
            title="Unsubscribe from exports"
            description={
                <p>
                    To make sure there's no unexpected impact on your data, you'll need to explicitly disable all of the
                    following apps before unsubscribing:
                </p>
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        loading={loading}
                        type="primary"
                        onClick={() => {}} // TODO: replace with the real unsubscribe callback
                        disabledReason={unsubscribeDisabled ? 'All the apps and batch exports explicitly first.' : null}
                    >
                        Unsubscribe
                    </LemonButton>
                </>
            }
        >
            <LemonTable
                dataSource={pluginConfigs}
                size="xs"
                loading={loading}
                columns={[
                    {
                        title: 'Name',
                        sticky: true,
                        render: function RenderPluginName(_, pluginConfig) {
                            return (
                                <>
                                    {pluginConfig.description && (
                                        <LemonMarkdown className="row-description" lowKeyHeadings>
                                            {pluginConfig.description}
                                        </LemonMarkdown>
                                    )}
                                </>
                            )
                        },
                    },
                    {
                        title: 'App',
                        render: function RenderAppInfo(_, pluginConfig) {
                            return <RenderApp plugin={plugins[pluginConfig.plugin]} />
                        },
                    },
                ]}
            />
            {/* "Show a table with team(project), plugin/export and disable" */}
        </LemonModal>
    )
}
