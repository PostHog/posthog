import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { DataModelingNode } from '~/types'

import { endpointModelUrl, parseEndpointModelName } from './endpointModelName'

export function ModelNameLink({ node }: { node: DataModelingNode }): JSX.Element {
    const endpointModel = node.type === 'endpoint' ? parseEndpointModelName(node.name) : null
    if (!endpointModel) {
        return <LemonTableLink to={urls.nodeDetail(node.id)} title={node.name} />
    }
    return (
        <LemonTableLink
            to={endpointModelUrl(node.name)}
            title={
                <>
                    <span className="whitespace-nowrap">{endpointModel.endpointName}</span>
                    <Tooltip title={`Version ${endpointModel.version} of this endpoint`}>
                        <LemonTag type="muted" size="small">
                            v{endpointModel.version}
                        </LemonTag>
                    </Tooltip>
                </>
            }
        />
    )
}
