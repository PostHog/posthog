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
import { userLogic } from 'scenes/userLogic'

export function AdvancedTab(): JSX.Element {
    const { user } = useValues(userLogic)
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
                closable
            />
            <Subtitle subtitle="Advanced Options" />
            <SourcePlugin />
            <CustomPlugin />
            <LocalPlugin />
            {user?.team?.plugins_opt_in && <DangerZone />}
        </>
    )
}
