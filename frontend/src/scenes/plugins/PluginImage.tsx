import { Card } from 'antd'
import { parseGithubRepoURL } from 'lib/utils'
import React, { useEffect, useState } from 'react'
import { CodeOutlined } from '@ant-design/icons'
import imgPluginDefault from 'public/plugin-default.svg'
import { PluginInstallationType } from 'scenes/plugins/types'

export function PluginImage({ url, pluginType }: { url?: string; pluginType?: PluginInstallationType }): JSX.Element {
    const [state, setState] = useState({ image: imgPluginDefault })

    useEffect(() => {
        if (url?.includes('github.com')) {
            const { user, repo } = parseGithubRepoURL(url)
            setState({ ...state, image: `https://raw.githubusercontent.com/${user}/${repo}/main/logo.png` })
        }
    }, [url])

    return (
        <Card
            style={{
                width: 60,
                height: 60,
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                marginLeft: 'auto',
                marginRight: 'auto',
            }}
            bodyStyle={{ padding: 4 }}
        >
            {pluginType === 'source' ? (
                <CodeOutlined style={{ fontSize: 32 }} />
            ) : (
                <img
                    src={state.image}
                    style={{ maxWidth: '100%', maxHeight: '100%' }}
                    alt=""
                    onError={() => setState({ ...state, image: imgPluginDefault })}
                />
            )}
        </Card>
    )
}
