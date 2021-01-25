import { Alert } from 'antd'
import { PluginTab } from 'scenes/plugins/types'
import { Subtitle } from 'lib/components/PageHeader'
import React from 'react'
import { SourcePlugin } from 'scenes/plugins/tabs/custom/SourcePlugin'
import { CustomPlugin } from 'scenes/plugins/tabs/custom/CustomPlugin'
import { LocalPlugin } from 'scenes/plugins/tabs/custom/LocalPlugin'
import { useActions } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

export function CustomTab(): JSX.Element {
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
            <Subtitle subtitle="Custom Plugins" />
            <SourcePlugin />
            <CustomPlugin />
            <LocalPlugin />
        </>
    )
}
