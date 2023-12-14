import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { organizationLogic } from 'scenes/organizationLogic'

import { exportsUnsubscribeModalLogic } from './exportsUnsubscribeModalLogic'

export function ExportsUnsubscribeModal(): JSX.Element {
    const { modalOpen, unsubscribeDisabledReason, loading, itemsToDisable } = useValues(exportsUnsubscribeModalLogic)
    const { closeModal, disablePlugin, pauseBatchExport, completeUnsubscribe } =
        useActions(exportsUnsubscribeModalLogic)
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
                        onClick={completeUnsubscribe}
                        disabledReason={unsubscribeDisabledReason}
                    >
                        Unsubscribe
                    </LemonButton>
                </>
            }
        >
            <LemonTable
                dataSource={itemsToDisable}
                size="xs"
                loading={loading}
                columns={[
                    {
                        title: 'Team',
                        render: function RenderTeam(_, item) {
                            return currentOrganization.teams.find((team) => team.id === item.team_id)?.name
                        },
                    },
                    {
                        render: function RenderAppInfo(_, item) {
                            return item.icon
                        },
                    },
                    {
                        title: 'Name',
                        render: function RenderPluginName(_, item) {
                            return (
                                <>
                                    <span className="row-name">{item.name}</span>
                                    {item.description && (
                                        <LemonMarkdown className="row-description" lowKeyHeadings>
                                            {item.description}
                                        </LemonMarkdown>
                                    )}
                                </>
                            )
                        },
                    },
                    {
                        title: '',
                        render: function RenderPluginDisable(_, item) {
                            return (
                                <LemonButton
                                    type="secondary"
                                    onClick={() => {
                                        if (item.plugin_config_id !== undefined) {
                                            disablePlugin(item.plugin_config_id)
                                        } else if (item.batch_export_id !== undefined) {
                                            pauseBatchExport(item.batch_export_id)
                                        }
                                    }}
                                    disabledReason={item.disabled ? 'Already disabled' : null}
                                >
                                    Disable
                                </LemonButton>
                            )
                        },
                    },
                ]}
            />
        </LemonModal>
    )
}
