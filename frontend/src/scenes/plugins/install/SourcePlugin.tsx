import React from 'react'
import { Button, Card, Col, Input, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginInstallationType } from 'scenes/plugins/types'

export function SourcePlugin(): JSX.Element {
    const { sourcePluginName, pluginError, loading } = useValues(pluginsLogic)
    const { setSourcePluginName, installPlugin } = useActions(pluginsLogic)

    return (
        <div style={{ marginTop: 16 }}>
            <Card>
                <h3 className="l3">Write The Code</h3>
                <p>
                    Write your plugin directly in PostHog.{' '}
                    <a href="https://posthog.com/docs/plugins/overview" target="_blank">
                        Read the documentation for more information!
                    </a>
                </p>
                <Row style={{ width: '100%' }} gutter={16}>
                    <Col style={{ flex: 1 }}>
                        <Input
                            value={sourcePluginName}
                            disabled={loading}
                            onChange={(e) => setSourcePluginName(e.target.value)}
                            placeholder={`For example: "Hourly Weather Sync Plugin"`}
                        />
                    </Col>
                    <Col>
                        <Button
                            disabled={loading || !sourcePluginName}
                            loading={loading}
                            type="default"
                            onClick={() => installPlugin(sourcePluginName, PluginInstallationType.Source)}
                        >
                            Start Coding
                        </Button>
                    </Col>
                </Row>
                {pluginError ? <p style={{ color: 'var(--red)', marginTop: 10 }}>{pluginError}</p> : null}
            </Card>
        </div>
    )
}
