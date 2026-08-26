import {
    ActivityChange,
    ActivityLogItem,
    Description,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

interface CanvasPostHogCapabilities {
    insights?: string[]
    captureEvents?: string[]
    inlineQueries?: boolean
    agentRequests?: boolean
}

function posthogCapabilities(value: unknown): CanvasPostHogCapabilities {
    if (value && typeof value === 'object' && 'posthog' in value) {
        return ((value as Record<string, unknown>).posthog ?? {}) as CanvasPostHogCapabilities
    }
    return {}
}

function listDiff(before: string[] | undefined, after: string[] | undefined): { added: string[]; removed: string[] } {
    const beforeSet = new Set(before ?? [])
    const afterSet = new Set(after ?? [])
    return {
        added: [...afterSet].filter((item) => !beforeSet.has(item)),
        removed: [...beforeSet].filter((item) => !afterSet.has(item)),
    }
}

export function describeCapabilitiesChange(change: ActivityChange): Description[] {
    const before = posthogCapabilities(change.before)
    const after = posthogCapabilities(change.after)
    const parts: Description[] = []

    const pushDiff = (verb: string, noun: string, items: string[]): void => {
        if (items.length > 0) {
            parts.push(
                <>
                    {verb} {noun}
                    {items.length === 1 ? '' : 's'} <strong>{items.join(', ')}</strong>
                </>
            )
        }
    }
    const insights = listDiff(before.insights, after.insights)
    pushDiff('declared', 'insight', insights.added)
    pushDiff('removed', 'insight', insights.removed)
    const events = listDiff(before.captureEvents, after.captureEvents)
    pushDiff('declared', 'capture event', events.added)
    pushDiff('removed', 'capture event', events.removed)

    if (!!before.inlineQueries !== !!after.inlineQueries) {
        parts.push(after.inlineQueries ? <>enabled inline queries</> : <>disabled inline queries</>)
    }
    if (!!before.agentRequests !== !!after.agentRequests) {
        parts.push(after.agentRequests ? <>enabled agent requests</> : <>disabled agent requests</>)
    }

    return parts
}

const BUILD_ACTIVITY_COPY: Record<string, string> = {
    build_retry: 'retried a build of',
    build_pin: 'pinned a build of',
    build_unpin: 'unpinned a build of',
    build_cancel: 'canceled a build of',
}

const inlineOrList = (parts: Description[]): JSX.Element =>
    parts.length === 1 ? (
        <> {parts[0]}</>
    ) : (
        <ul className="bullet-list">
            {parts.map((part, index) => (
                <li key={index}>{part}</li>
            ))}
        </ul>
    )

const canvasUpdateFieldCopy = (change: ActivityChange): Description | null => {
    if (change.field === 'name') {
        return (
            <>
                renamed it from <strong>{change.before as string}</strong> to <strong>{change.after as string}</strong>
            </>
        )
    }
    if (change.field === 'pinned') {
        return change.after ? <>pinned it to its channel</> : <>unpinned it from its channel</>
    }
    if (change.field === 'context') {
        return <>updated its context</>
    }
    return null
}

export function canvasActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'Canvas') {
        console.error('canvas describer received a non-canvas activity')
        return { description: null }
    }

    const actor = <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong>
    const canvasName = <strong>{logItem.detail.name || 'Untitled canvas'}</strong>

    if (logItem.activity === 'published') {
        const capabilitiesChange = (logItem.detail.changes || []).find((change) => change.field === 'capabilities')
        const parts = capabilitiesChange ? describeCapabilitiesChange(capabilitiesChange) : []
        return {
            description: (
                <>
                    {actor} published canvas {canvasName}
                    {parts.length === 1 ? <> and</> : null}
                    {parts.length > 1 ? <> and changed its declared capabilities:</> : null}
                    {parts.length > 0 ? inlineOrList(parts) : null}
                </>
            ),
        }
    }

    if (logItem.activity === 'drafted') {
        const capabilitiesChange = (logItem.detail.changes || []).find((change) => change.field === 'capabilities')
        const parts = capabilitiesChange ? describeCapabilitiesChange(capabilitiesChange) : []
        return {
            description: (
                <>
                    {actor} drafted a new version of canvas {canvasName}
                    {parts.length === 1 ? <> that</> : null}
                    {parts.length > 1 ? <> that changes its declared capabilities:</> : null}
                    {parts.length > 0 ? inlineOrList(parts) : null}
                </>
            ),
        }
    }

    if (logItem.activity === 'reverted') {
        return {
            description: (
                <>
                    {actor} reverted canvas {canvasName} to an earlier version
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        const parts = (logItem.detail.changes || []).map(canvasUpdateFieldCopy).filter(Boolean) as Description[]
        if (parts.length > 0) {
            return {
                description: (
                    <>
                        {actor} updated canvas {canvasName}:{inlineOrList(parts)}
                    </>
                ),
            }
        }
    }

    const buildCopy = BUILD_ACTIVITY_COPY[logItem.activity]
    if (buildCopy) {
        return {
            description: (
                <>
                    {actor} {buildCopy} canvas {canvasName}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, canvasName)
}
