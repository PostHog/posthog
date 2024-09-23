import { IconTerminal } from '@posthog/icons'
import { parseGithubRepoURL } from 'lib/utils'
import imgPluginDefault from 'public/plugin-default.svg'
import IconTransformationSemverFlattener from 'public/transformations/semver-flattener.png'
import IconTransformationUserAgent from 'public/transformations/user-agent.png'
import { useEffect, useState } from 'react'

import { PluginType } from '~/types'

const pluginImageOverrides: Record<string, any> = {
    'inline://semver-flattener': IconTransformationSemverFlattener,
    'inline://user-agent': IconTransformationUserAgent,
}

export type PluginImageSize = 'small' | 'medium' | 'large'

export function PluginImage({
    plugin,
    size = 'medium',
}: {
    plugin: Partial<Pick<PluginType, 'plugin_type' | 'url' | 'icon'>>
    size?: PluginImageSize
}): JSX.Element {
    const { plugin_type: pluginType, url, icon } = plugin
    const [state, setState] = useState({ image: imgPluginDefault })
    const pixelSize = {
        large: 100,
        medium: 60,
        small: 30,
    }[size]

    useEffect(() => {
        const imageOverride = pluginImageOverrides[url ?? '']
        if (imageOverride) {
            setState((state) => ({ ...state, image: imageOverride }))
        } else if (icon) {
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
        <IconTerminal
            className="plugin-image shrink-0 ml-0"
            style={{
                fontSize: pixelSize,
            }}
        />
    ) : (
        <div
            className="plugin-image shrink-0 bg-contain bg-no-repeat"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: pixelSize,
                height: pixelSize,
                backgroundImage: `url(${state.image})`,
            }}
            // eslint-disable-next-line react/no-unknown-property
            onError={() => setState({ ...state, image: imgPluginDefault })}
        />
    )
}
