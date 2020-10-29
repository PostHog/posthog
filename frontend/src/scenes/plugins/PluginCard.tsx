import { Col, Card, Button, Switch } from 'antd'
import { useActions } from 'kea'
import React, { useEffect, useState } from 'react'
import { pluginsLogic } from './pluginsLogic'
import imgPluginDefault from 'public/plugin-default.svg'
import { ellipsis, parseGithubRepoURL } from 'lib/utils'
import { PluginConfigType } from '~/types'
import { PlusOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'

interface PluginCardType {
    name: string
    description: string
    url: string
    pluginConfig?: PluginConfigType
    pluginId?: number
}

export function PluginCard({ name, description, url, pluginConfig, pluginId }: PluginCardType): JSX.Element {
    const { editPlugin, toggleEnabled, installPlugin } = useActions(pluginsLogic)
    const [state, setState] = useState({ image: imgPluginDefault })

    useEffect(() => {
        if (url.includes('github.com')) {
            const { user, repo } = parseGithubRepoURL(url)
            setState({ ...state, image: `https://raw.githubusercontent.com/${user}/${repo}/main/logo.png` })
        }
    }, [])

    return (
        <Col sm={6}>
            <Card
                style={{ height: '100%', display: 'flex' }}
                bodyStyle={{ display: 'flex', flexDirection: 'column', flexGrow: 1 }}
            >
                <Card
                    className="card-elevated"
                    style={{
                        width: 60,
                        height: 60,
                        marginBottom: 24,
                        display: 'flex',
                        justifyContent: 'center',
                        alignItems: 'center',
                        marginLeft: 'auto',
                        marginRight: 'auto',
                    }}
                    bodyStyle={{ padding: 4 }}
                >
                    <img
                        src={state.image}
                        style={{ maxWidth: '100%', maxHeight: '100%' }}
                        alt=""
                        onError={() => setState({ ...state, image: imgPluginDefault })}
                    />
                </Card>
                <div className="text-center oh-spaced-bottom">
                    <b>{name}</b>
                </div>
                <div style={{ flexGrow: 1, paddingBottom: 16 }}>{ellipsis(description, 180)}</div>
                <div style={{ display: 'flex' }}>
                    <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
                        {pluginConfig && (
                            <>
                                <Switch
                                    checked={pluginConfig.enabled}
                                    onChange={(enabled) => toggleEnabled({ id: pluginConfig.id, enabled })}
                                />
                                {pluginConfig.global && (
                                    <div style={{ paddingTop: 4 }} className="text-extra-small text-muted">
                                        Globally enabled
                                    </div>
                                )}
                            </>
                        )}
                        {!pluginConfig && (
                            <>
                                <Link to={url} target="_blank" rel="noopener noreferrer">
                                    Learn more
                                </Link>
                            </>
                        )}
                    </div>
                    <div>
                        {pluginId && (
                            <Button type="primary" onClick={() => editPlugin(pluginId)}>
                                Configure
                            </Button>
                        )}
                        {!pluginId && (
                            <Button type="primary" onClick={() => installPlugin(url)} icon={<PlusOutlined />}>
                                Install
                            </Button>
                        )}
                    </div>
                </div>
            </Card>
        </Col>
    )
}
