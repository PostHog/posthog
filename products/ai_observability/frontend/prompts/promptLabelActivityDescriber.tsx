import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'

// detail.name is "{prompt name}: {label name}" (set in backend activity_logging.py).
// The first ": " is always the separator: prompt names only allow [a-zA-Z0-9_-]
// (validate_prompt_name_value) and label names only allow lowercase [a-z0-9._-]
// (validate_prompt_label_name_value), so neither can contain a colon or a space.
function parseDetailName(logItem: ActivityLogItem): { promptName: string; labelName: string } {
    const name = logItem?.detail?.name ?? ''
    const separatorIndex = name.indexOf(': ')
    if (separatorIndex === -1) {
        return { promptName: '', labelName: name }
    }
    return { promptName: name.slice(0, separatorIndex), labelName: name.slice(separatorIndex + 2) }
}

export function promptLabelActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const user = userNameForLogItem(logItem)
    const { promptName, labelName } = parseDetailName(logItem)
    const change = logItem.detail?.changes?.[0]
    const onPrompt = promptName ? (
        <>
            {' '}
            on prompt <b>{promptName}</b>
        </>
    ) : null

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{user}</strong> created label <b>{labelName}</b> pointing at{' '}
                    <b>v{String(change?.after ?? '?')}</b>
                    {onPrompt}
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{user}</strong> moved label <b>{labelName}</b> from{' '}
                    <b>v{String(change?.before ?? '?')}</b> to <b>v{String(change?.after ?? '?')}</b>
                    {onPrompt}
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{user}</strong> removed label <b>{labelName}</b> (was pointing at{' '}
                    <b>v{String(change?.before ?? '?')}</b>){onPrompt}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, labelName)
}
