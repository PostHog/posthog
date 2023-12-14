import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { organizationLogic } from 'scenes/organizationLogic'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

import { RenderApp } from '../utils'
import { exportsUnsubscribeModalLogic } from './exportsUnsubscribeModalLogic'

export function ExportsUnsubscribeModal(): JSX.Element {
    const { plugins } = useValues(pluginsLogic)
    const { modalOpen, unsubscribeDisabledReason, loading, pluginConfigsToDisable } =
        useValues(exportsUnsubscribeModalLogic)
    const { closeModal, disablePlugin } = useActions(exportsUnsubscribeModalLogic)
    const { currentOrganization } = useValues(organizationLogic)

    if (!currentOrganization) {
        return <></>
    }

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
                        disabledReason={unsubscribeDisabledReason}
                    >
                        Unsubscribe
                    </LemonButton>
                </>
            }
        >
            <LemonTable
                dataSource={Object.values(pluginConfigsToDisable)}
                size="xs"
                loading={loading}
                columns={[
                    {
                        title: 'Team',
                        render: function RenderTeam(_, pluginConfig) {
                            return currentOrganization.teams.find((team) => team.id === pluginConfig.team_id)?.name
                        },
                    },
                    {
                        render: function RenderAppInfo(_, pluginConfig) {
                            return <RenderApp plugin={plugins[pluginConfig.plugin]} />
                        },
                    },
                    {
                        title: 'Name',
                        render: function RenderPluginName(_, pluginConfig) {
                            return (
                                <>
                                    <span className="row-name">{pluginConfig.name}</span>
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
                        title: '',
                        render: function RenderPluginDisable(_, pluginConfig) {
                            return (
                                <LemonButton
                                    type="secondary"
                                    onClick={() => disablePlugin(pluginConfig.id)}
                                    disabledReason={pluginConfig.enabled ? null : 'Already disabled'}
                                >
                                    Disable
                                </LemonButton>
                            )
                        },
                    },
                ]}
            />
            {/* "Show a table with team(project), plugin/export and disable" */}
        </LemonModal>
    )
}
