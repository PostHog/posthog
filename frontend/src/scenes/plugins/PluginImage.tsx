import { Card } from 'antd'
import { parseGithubRepoURL } from 'lib/utils'
import React, { useEffect, useState } from 'react'
import imgPluginDefault from 'public/plugin-default.svg'

export function PluginImage({ url }: { url: string }): JSX.Element {
    const [state, setState] = useState({ image: imgPluginDefault })

    useEffect(() => {
        if (url.includes('github.com')) {
            const { user, repo } = parseGithubRepoURL(url)
            setState({ ...state, image: `https://raw.githubusercontent.com/${user}/${repo}/main/logo.png` })
        }
    }, [])

    return (
        <Card
            /* TODO: when #2114 is merged className="card-elevated" */
            style={{
                width: 60,
                height: 60,
                marginBottom: 24,
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                marginLeft: 'auto',
                marginRight: 'auto',
                boxShadow: '0px 80px 80px rgba(0, 0, 0, 0.075), 0px 10px 10px rgba(0, 0, 0, 0.035) !important',
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
    )
}
