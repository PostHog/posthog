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

    const insights = listDiff(before.insights, after.insights)
    if (insights.added.length > 0) {
        parts.push(
            <>
                declared {insights.added.length === 1 ? 'insight' : 'insights'}{' '}
                <strong>{insights.added.join(', ')}</strong>
            </>
        )
    }
    if (insights.removed.length > 0) {
        parts.push(
            <>
                removed {insights.removed.length === 1 ? 'insight' : 'insights'}{' '}
                <strong>{insights.removed.join(', ')}</strong>
            </>
        )
    }

    const events = listDiff(before.captureEvents, after.captureEvents)
    if (events.added.length > 0) {
        parts.push(
            <>
                declared capture {events.added.length === 1 ? 'event' : 'events'}{' '}
                <strong>{events.added.join(', ')}</strong>
            </>
        )
    }
    if (events.removed.length > 0) {
        parts.push(
            <>
                removed capture {events.removed.length === 1 ? 'event' : 'events'}{' '}
                <strong>{events.removed.join(', ')}</strong>
            </>
        )
    }

    if (!!before.inlineQueries !== !!after.inlineQueries) {
        parts.push(after.inlineQueries ? <>enabled inline queries</> : <>disabled inline queries</>)
    }

    return parts
}

const BUILD_ACTIVITY_COPY: Record<string, string> = {
    build_retry: 'retried a build of',
    build_pin: 'pinned a build of',
    build_unpin: 'unpinned a build of',
    build_cancel: 'canceled a build of',
}

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
        if (parts.length === 0) {
            return {
                description: (
                    <>
                        {actor} published canvas {canvasName}
                    </>
                ),
            }
        }
        if (parts.length === 1) {
            return {
                description: (
                    <>
                        {actor} published canvas {canvasName} and {parts[0]}
                    </>
                ),
            }
        }
        return {
            description: (
                <>
                    {actor} published canvas {canvasName} and changed its declared capabilities:
                    <ul className="bullet-list">
                        {parts.map((part, index) => (
                            <li key={index}>{part}</li>
                        ))}
                    </ul>
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
        const parts: Description[] = []
        for (const change of logItem.detail.changes || []) {
            const part = canvasUpdateFieldCopy(change)
            if (part) {
                parts.push(part)
            }
        }
        if (parts.length === 1) {
            return {
                description: (
                    <>
                        {actor} updated canvas {canvasName}: {parts[0]}
                    </>
                ),
            }
        }
        if (parts.length > 1) {
            return {
                description: (
                    <>
                        {actor} updated canvas {canvasName}:
                        <ul className="bullet-list">
                            {parts.map((part, index) => (
                                <li key={index}>{part}</li>
                            ))}
                        </ul>
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
