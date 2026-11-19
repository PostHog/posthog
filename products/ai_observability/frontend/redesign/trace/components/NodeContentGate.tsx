import { ReactNode } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import type { TraceNodeDetailApi } from '../../../generated/api.schemas'
import { LoadFailure, NodeLoad } from '../types'
import { ErrorCallout } from './ErrorCallout'

const LOAD_ERRORS: Record<LoadFailure, string> = {
    not_found: 'This step could not be found. It may have been deleted, or it is outside the retention period.',
    failed: 'This step could not be loaded. Select it again to retry.',
}

export interface NodeContentGateProps {
    load: NodeLoad
    children: (node: TraceNodeDetailApi) => ReactNode
}

export function NodeContentGate({ load, children }: NodeContentGateProps): JSX.Element {
    if (load.status === 'loading') {
        return <LemonSkeleton repeat={3} className="h-16" />
    }
    if (load.status === 'error') {
        return <ErrorCallout message={LOAD_ERRORS[load.failure]} />
    }
    return <>{children(load.node)}</>
}
