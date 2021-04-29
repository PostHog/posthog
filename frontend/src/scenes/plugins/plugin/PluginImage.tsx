import { parseGithubRepoURL } from 'lib/utils'
import React, { useEffect, useState } from 'react'
import { CodeOutlined } from '@ant-design/icons'
import imgPluginDefault from 'public/plugin-default.svg'
import { PluginInstallationType } from 'scenes/plugins/types'

export function PluginImage({
    url,
    pluginType,
    size = 'medium',
}: {
    url?: string
    pluginType?: PluginInstallationType
    size?: 'small' | 'medium' | 'large'
}): JSX.Element {
    const [state, setState] = useState({ image: imgPluginDefault })
    let pixelSize: number
    switch (size) {
        case 'large':
            pixelSize = 100
            break
        case 'small':
            pixelSize = 40
            break
        case 'medium':
        default:
            pixelSize = 60
            break
    }

    useEffect(() => {
        if (url?.includes('github.com')) {
            const { user, repo } = parseGithubRepoURL(url)
            setState({ ...state, image: `https://raw.githubusercontent.com/${user}/${repo}/main/logo.png` })
        }
    }, [url])

    return pluginType === 'source' ? (
        <CodeOutlined style={{ fontSize: pixelSize }} className="plugin-image" />
    ) : (
        <div
            className="plugin-image"
            style={{
                width: pixelSize,
                height: pixelSize,
                backgroundImage: `url(${state.image})`,
                backgroundSize: 'contain',
                backgroundRepeat: 'no-repeat',
            }}
            onError={() => setState({ ...state, image: imgPluginDefault })}
        />
    )
}
