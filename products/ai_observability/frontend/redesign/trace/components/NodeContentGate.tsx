import { ReactNode } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { LoadedNodeContent, NodeContent } from '../types'
import { ErrorCallout } from './ErrorCallout'

export interface NodeContentGateProps {
    content: NodeContent
    children: (content: LoadedNodeContent) => ReactNode
}

export function NodeContentGate({ content, children }: NodeContentGateProps): JSX.Element {
    if (content.kind === 'loading') {
        return <LemonSkeleton repeat={3} className="h-16" />
    }
    if (content.kind === 'error') {
        return <ErrorCallout message={content.message} />
    }
    return <>{children(content)}</>
}
