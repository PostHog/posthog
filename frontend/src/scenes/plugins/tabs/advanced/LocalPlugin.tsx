import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginInstallationType } from 'scenes/plugins/types'
import Title from 'antd/lib/typography/Title'
import Paragraph from 'antd/lib/typography/Paragraph'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

export function LocalPlugin(): JSX.Element {
    const { localPluginUrl, pluginError, loading } = useValues(pluginsLogic)
    const { setLocalPluginUrl, installPlugin } = useActions(pluginsLogic)

    return (
        <div className="border rounded p-4">
            <Title level={5}>Install Local App</Title>
            <Paragraph>To install a local app from this computer/server, give its full path below.</Paragraph>

            <div className="flex flex-1 space-x-2">
                <LemonInput
                    value={localPluginUrl}
                    disabled={loading}
                    onChange={(value) => setLocalPluginUrl(value)}
                    placeholder="/var/posthog/plugins/helloworldplugin"
                    fullWidth={true}
                    size="small"
                />
                <LemonButton
                    disabledReason={loading || !localPluginUrl ? 'Enter a plugin URL' : undefined}
                    loading={loading}
                    onClick={() => installPlugin(localPluginUrl, PluginInstallationType.Local)}
                    size="small"
                    status="muted"
                    type="secondary"
                >
                    Install
                </LemonButton>
            </div>
            {pluginError ? <p style={{ color: 'var(--red)', marginTop: 10 }}>{pluginError}</p> : null}
        </div>
    )
}
