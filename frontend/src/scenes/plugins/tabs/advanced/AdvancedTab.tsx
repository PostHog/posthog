import { Alert } from 'antd'
import { PluginTab } from 'scenes/plugins/types'
import { Subtitle } from 'lib/components/PageHeader'
import React from 'react'
import { SourcePlugin } from 'scenes/plugins/tabs/advanced/SourcePlugin'
import { CustomPlugin } from 'scenes/plugins/tabs/advanced/CustomPlugin'
import { LocalPlugin } from 'scenes/plugins/tabs/advanced/LocalPlugin'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { DangerZone } from 'scenes/plugins/tabs/advanced/DangerZone'
import { teamLogic } from 'scenes/teamLogic'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

export function AdvancedTab(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { currentTeam } = useValues(teamLogic)
    const { setPluginTab } = useActions(pluginsLogic)
    return (
        <>
            <Alert
                message="Advanced Features Ahead"
                description={
                    <>
                        Create and install your <b>own plugins</b> or plugins from <b>third-parties</b>. If you're
                        looking for officially supported plugins, try the{' '}
                        <a
                            href="#"
                            onClick={(e) => {
                                e.preventDefault()
                                setPluginTab(PluginTab.Repository)
                            }}
                        >
                            Plugin Repository
                        </a>
                        .
                    </>
                }
                type="warning"
                showIcon
            />
            <Subtitle subtitle="Advanced Options" />
            <SourcePlugin />
            <CustomPlugin />
            {preflight && !preflight.cloud && <LocalPlugin />}
            {currentTeam?.plugins_opt_in && <DangerZone />}
        </>
    )
}
