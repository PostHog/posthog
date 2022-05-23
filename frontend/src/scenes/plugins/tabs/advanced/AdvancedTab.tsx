import { Alert } from 'antd'
import { PluginTab } from 'scenes/plugins/types'
import { Subtitle } from 'lib/components/PageHeader'
import React from 'react'
import { SourcePlugin } from 'scenes/plugins/tabs/advanced/SourcePlugin'
import { CustomPlugin } from 'scenes/plugins/tabs/advanced/CustomPlugin'
import { LocalPlugin } from 'scenes/plugins/tabs/advanced/LocalPlugin'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export function AdvancedTab(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { setPluginTab } = useActions(pluginsLogic)

    return (
        <>
            <Alert
                message="Advanced Features Ahead"
                description={
                    <>
                        Create and install your <b>own apps</b> or apps from <b>third-parties</b>. If you're looking for
                        officially supported apps, try the{' '}
                        <a
                            href="#"
                            onClick={(e) => {
                                e.preventDefault()
                                setPluginTab(PluginTab.Repository)
                            }}
                        >
                            App Repository
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
        </>
    )
}
