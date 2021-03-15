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

    return pluginType === 'source' ? (
        <CodeOutlined style={{ fontSize: 80 }} className="plugin-image" />
    ) : (
        <img
            className="plugin-image"
            src={state.image}
            style={{ maxWidth: 'calc(min(100%, 80px))', maxHeight: 'calc(min(100%, 120px))' }}
            alt=""
            onError={() => setState({ ...state, image: imgPluginDefault })}
        />
    )
}
