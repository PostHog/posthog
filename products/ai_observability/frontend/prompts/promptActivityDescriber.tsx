import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

function changeAfter(logItem: ActivityLogItem, field: string): string | null {
    const change = logItem.detail?.changes?.find((c) => c.field === field)
    return change?.after != null ? String(change.after) : null
}

function changeBefore(logItem: ActivityLogItem, field: string): string | null {
    const change = logItem.detail?.changes?.find((c) => c.field === field)
    return change?.before != null ? String(change.before) : null
}

// Lifecycle events (create/publish/archive/duplicate) for scope LLMPrompt, written by
// log_llm_prompt_activity in backend activity_logging.py. detail.name is the prompt name.
export function promptActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const user = userNameForLogItem(logItem)
    const promptName = logItem?.detail?.name ?? ''

    if (logItem.activity === 'created') {
        const duplicatedFrom = changeAfter(logItem, 'duplicated_from')
        return {
            description: duplicatedFrom ? (
                <>
                    <strong className="ph-no-capture">{user}</strong> created prompt <b>{promptName}</b> as a copy of{' '}
                    <b>{duplicatedFrom}</b>
                </>
            ) : (
                <>
                    <strong className="ph-no-capture">{user}</strong> created prompt <b>{promptName}</b>
                </>
            ),
        }
    }

    if (logItem.activity === 'published') {
        const version = changeAfter(logItem, 'version')
        const versionDescription = changeAfter(logItem, 'version_description')
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{user}</strong> published <b>v{version ?? '?'}</b> of prompt{' '}
                    <b>{promptName}</b>
                    {versionDescription ? <>: "{versionDescription}"</> : null}
                </>
            ),
        }
    }

    if (logItem.activity === 'archived') {
        const versionCount = changeBefore(logItem, 'version_count')
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{user}</strong> archived prompt <b>{promptName}</b>
                    {versionCount ? <> ({versionCount} versions)</> : null}
                </>
            ),
        }
    }

    if (logItem.activity === 'duplicated') {
        const duplicatedTo = changeAfter(logItem, 'duplicated_to')
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{user}</strong> duplicated prompt <b>{promptName}</b>
                    {duplicatedTo ? (
                        <>
                            {' '}
                            to <b>{duplicatedTo}</b>
                        </>
                    ) : null}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, promptName)
}
