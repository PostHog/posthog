import { IconCheckCircle } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { exportsUnsubscribeTableLogic } from './exportsUnsubscribeTableLogic'
import { organizationTeamsLogic } from 'scenes/organizationTeamsLogic'

export function ExportsUnsubscribeTable(): JSX.Element {
    const { loading, itemsToDisable } = useValues(exportsUnsubscribeTableLogic)
    const { disablePlugin, pauseBatchExport, disableHogFunction } = useActions(exportsUnsubscribeTableLogic)
    const { teams } = useValues(organizationTeamsLogic)

    if (!teams) {
        return <></>
    }

    return (
        <LemonTable
            dataSource={itemsToDisable}
            size="small"
            loading={loading}
            columns={[
                {
                    width: 0,
                    render: function RenderAppInfo(_, item) {
                        return item.icon
                    },
                },
                {
                    title: 'App name',
                    render: function RenderPluginName(_, item) {
                        return (
                            <>
                                <LemonTableLink to={item.url} title={item.name} description={item.description} />
                            </>
                        )
                    },
                },
                {
                    title: 'Project',
                    render: function RenderTeam(_, item) {
                        return teams.find((team) => team.id === item.team_id)?.name
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
                                    } else if (item.hog_function_id !== undefined) {
                                        disableHogFunction(item.hog_function_id)
                                    }
                                }}
                                disabledReason={item.disabled ? 'Already disabled' : null}
                                icon={item.disabled ? <IconCheckCircle /> : undefined}
                            >
                                {item.disabled ? 'Disabled' : 'Disable'}
                            </LemonButton>
                        )
                    },
                },
            ]}
        />
    )
}
