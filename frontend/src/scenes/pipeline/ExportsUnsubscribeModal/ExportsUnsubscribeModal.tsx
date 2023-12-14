import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

import { RenderApp } from '../utils'
import { exportsUnsubscribeModalLogic } from './exportsUnsubscribeModalLogic'

export function ExportsUnsubscribeModal(): JSX.Element {
    const { plugins } = useValues(pluginsLogic)
    const { modalOpen, unsubscribeDisabled, loading, pluginConfigsToDisable } = useValues(exportsUnsubscribeModalLogic)
    const { closeModal } = useActions(exportsUnsubscribeModalLogic)

    return (
        <LemonModal
            onClose={closeModal}
            isOpen={modalOpen}
            width={600}
            title="Disable remaining export apps"
            description="To make sure there's no unexpected impact on your data, you need to explicitly disable the following apps before unsubscribing:"
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
                dataSource={pluginConfigsToDisable}
                size="xs"
                loading={loading}
                columns={[
                    {
                        render: function RenderAppInfo(_, pluginConfig) {
                            return <RenderApp plugin={plugins[pluginConfig.plugin]} />
                        },
                    },
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
                ]}
            />
            {/* "Show a table with team(project), plugin/export and disable" */}
        </LemonModal>
    )
}
