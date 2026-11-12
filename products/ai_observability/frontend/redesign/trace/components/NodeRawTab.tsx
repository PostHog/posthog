import { LemonSkeleton } from '@posthog/lemon-ui'

import { JSONViewer } from 'lib/components/JSONViewer'

import type { TraceNodeEventApi } from '../../../generated/api.schemas'
import { LoadFailure, RawLoad } from '../types'
import { ErrorCallout } from './ErrorCallout'

export interface NodeRawTabProps {
    raw: RawLoad | undefined
}

const RAW_LOAD_ERRORS: Record<LoadFailure, string> = {
    not_found: 'This event could not be found. It may have been deleted, or it is outside the retention period.',
    failed: 'This event could not be loaded. Select the step again to retry.',
}

function displayEvent({ name, uuid, timestamp, properties }: TraceNodeEventApi): Record<string, unknown> {
    return { event: name, uuid, timestamp, properties }
}

export function NodeRawTab({ raw }: NodeRawTabProps): JSX.Element {
    if (!raw || raw.status === 'loading') {
        return <LemonSkeleton repeat={3} className="h-16" />
    }
    if (raw.status === 'error') {
        return <ErrorCallout message={RAW_LOAD_ERRORS[raw.failure]} />
    }
    if (!raw.raw.event) {
        return (
            <p className="m-0 text-secondary">
                This trace has no event of its own, so there is no raw event to show. Select a step to see its raw
                event.
            </p>
        )
    }
    return (
        <div className="overflow-auto rounded border border-primary bg-surface-primary p-2">
            <JSONViewer src={displayEvent(raw.raw.event)} name={null} collapsed={2} sortKeys />
        </div>
    )
}
