import { parseGithubRepoURL } from 'lib/utils'
import { useEffect, useState } from 'react'
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
    size?: 'medium' | 'large'
}): JSX.Element {
    const [state, setState] = useState({ image: imgPluginDefault })
    const pixelSize = size === 'large' ? 100 : 60

    useEffect(() => {
        if (url?.includes('github.com')) {
            try {
                const { user, repo, branch, path } = parseGithubRepoURL(url)
                setState({
                    ...state,
                    image: `https://raw.githubusercontent.com/${user}/${repo}/${branch}/${path}/logo.png`,
                })
            } catch (e) {
                // parseGithubRepoURL throws if the github URL is in a bad format. We don't want the component to crash then.
                console.log(e)
            }
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
