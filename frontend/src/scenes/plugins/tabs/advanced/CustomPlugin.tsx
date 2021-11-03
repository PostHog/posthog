import React from 'react'
import { Button, Card, Col, Input, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginInstallationType } from 'scenes/plugins/types'
import Title from 'antd/lib/typography/Title'
import Paragraph from 'antd/lib/typography/Paragraph'

export function CustomPlugin(): JSX.Element {
    const { customPluginUrl, pluginError, loading } = useValues(pluginsLogic)
    const { setCustomPluginUrl, installPlugin } = useActions(pluginsLogic)

    return (
        <div style={{ marginTop: 16 }}>
            <Card>
                <Title level={5}>Install from GitHub, GitLab or npm</Title>
                <Paragraph>
                    To install a third-party or custom plugin, paste its URL below. For{' '}
                    <a
                        href="https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        GitHub
                    </a>
                    {', '}
                    <a
                        href="https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        GitLab
                    </a>
                    {' and '}
                    <a
                        href="https://docs.npmjs.com/creating-and-viewing-access-tokens"
                        target="_blank"
                        rel="noopener noreferrer"
                    >
                        npm
                    </a>{' '}
                    private repositories, append <code>?private_token=TOKEN</code> to the end of the URL.
                    <br />
                    <b className="text-warning">Warning: Only install plugins from trusted sources.</b>
                </Paragraph>

                <Row style={{ width: '100%' }} gutter={16}>
                    <Col style={{ flex: 1 }}>
                        <Input
                            value={customPluginUrl}
                            disabled={loading}
                            onChange={(e) => setCustomPluginUrl(e.target.value)}
                            placeholder="https://github.com/user/repo"
                        />
                    </Col>
                    <Col>
                        <Button
                            disabled={loading || !customPluginUrl}
                            loading={loading}
                            type="default"
                            onClick={() => installPlugin(customPluginUrl, PluginInstallationType.Custom)}
                        >
                            Fetch and install
                        </Button>
                    </Col>
                </Row>
                {pluginError ? <p style={{ color: 'var(--red)', marginTop: 10 }}>{pluginError}</p> : null}
            </Card>
        </div>
    )
}
