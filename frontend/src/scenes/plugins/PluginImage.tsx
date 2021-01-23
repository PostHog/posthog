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
        <div className="plugin-image">
            {pluginType === 'source' ? (
                <CodeOutlined style={{ fontSize: 40 }} />
            ) : (
                <img
                    src={state.image}
                    style={{ maxWidth: '100%', maxHeight: '100%' }}
                    alt=""
                    onError={() => setState({ ...state, image: imgPluginDefault })}
                />
            )}
        </div>
    )
}
