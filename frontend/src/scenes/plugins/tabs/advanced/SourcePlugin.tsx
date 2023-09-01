import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginInstallationType } from 'scenes/plugins/types'
import Title from 'antd/lib/typography/Title'
import Paragraph from 'antd/lib/typography/Paragraph'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

export function SourcePlugin(): JSX.Element {
    const { sourcePluginName, pluginError, loading } = useValues(pluginsLogic)
    const { setSourcePluginName, installPlugin } = useActions(pluginsLogic)

    return (
        <div className="border rounded p-4">
            <Title level={5}>App editor</Title>
            <Paragraph>
                Write your app directly in PostHog.{' '}
                <a href="https://posthog.com/docs/apps" target="_blank">
                    Read the documentation for more information!
                </a>
            </Paragraph>
            <div className="flex flex-1 space-x-2">
                <LemonInput
                    value={sourcePluginName}
                    disabled={loading}
                    onChange={(value) => setSourcePluginName(value)}
                    placeholder={`For example: "Hourly Weather Sync App"`}
                    fullWidth={true}
                    size="small"
                />

                <LemonButton
                    disabledReason={loading || !sourcePluginName ? 'Enter a plugin name' : undefined}
                    loading={loading}
                    onClick={() => installPlugin(sourcePluginName, PluginInstallationType.Source)}
                    size="small"
                    status="muted"
                    type="secondary"
                >
                    Start coding
                </LemonButton>
            </div>
            {pluginError ? <p style={{ color: 'var(--red)', marginTop: 10 }}>{pluginError}</p> : null}
        </div>
    )
}
