import { parseGithubRepoURL } from 'lib/utils'
import { useEffect, useState } from 'react'
import { CodeOutlined } from '@ant-design/icons'
import imgPluginDefault from 'public/plugin-default.svg'
import { PluginInstallationType } from 'scenes/plugins/types'

export function PluginImage({
    url,
    icon,
    pluginType,
    size = 'medium',
}: {
    url?: string
    icon?: string
    pluginType?: PluginInstallationType
    size?: 'medium' | 'large'
}): JSX.Element {
    const [state, setState] = useState({ image: imgPluginDefault })
    const pixelSize = size === 'large' ? 100 : 60

    useEffect(() => {
        if (icon) {
            setState((state) => ({ ...state, image: icon }))
        } else if (url?.includes('github.com')) {
            const { user, repo, path } = parseGithubRepoURL(url)

            setState({
                ...state,
                image: `https://raw.githubusercontent.com/${user}/${repo}/${path || 'main'}/logo.png`,
            })
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
            // eslint-disable-next-line react/no-unknown-property
            onError={() => setState({ ...state, image: imgPluginDefault })}
        />
    )
}
