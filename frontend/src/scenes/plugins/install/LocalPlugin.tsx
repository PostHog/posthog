import React from 'react'
import { Button, Card, Col, Input, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginInstallationType } from 'scenes/plugins/types'

export function LocalPlugin(): JSX.Element {
    const { localPluginUrl, pluginError, loading } = useValues(pluginsLogic)
    const { setLocalPluginUrl, installPlugin } = useActions(pluginsLogic)

    return (
        <div style={{ marginTop: 16 }}>
            <Card>
                <h3 className="l3">Install Local Plugin</h3>
                <p>To install a local plugin from this computer/server, give its full path below.</p>

                <Row style={{ width: '100%' }} gutter={16}>
                    <Col style={{ flex: 1 }}>
                        <Input
                            value={localPluginUrl}
                            disabled={loading}
                            onChange={(e) => setLocalPluginUrl(e.target.value)}
                            placeholder="/var/posthog/plugins/helloworldplugin"
                        />
                    </Col>
                    <Col>
                        <Button
                            disabled={loading || !localPluginUrl}
                            loading={loading}
                            type="default"
                            onClick={() => installPlugin(localPluginUrl, PluginInstallationType.Local)}
                        >
                            Install
                        </Button>
                    </Col>
                </Row>
                {pluginError ? <p style={{ color: 'var(--red)', marginTop: 10 }}>{pluginError}</p> : null}
            </Card>
        </div>
    )
}
