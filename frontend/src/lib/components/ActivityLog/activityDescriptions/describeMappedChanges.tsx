import {
    ActivityChange,
    ActivityLogItem,
    ActivityLogUserName,
    ChangeMapping,
    Description,
    HumanizedChange,
    activityLogSummary,
} from '../humanizeActivity'
import { SentenceList } from '../SentenceList'

export function describeMappedChanges(
    logItem: ActivityLogItem,
    mapping: Record<string, (change: ActivityChange, logItem: ActivityLogItem) => ChangeMapping | null>,
    target: Description,
    defaultSuffix: Description
): HumanizedChange | null {
    const descriptions: Description[] = []
    const summaries: Description[] = []
    let preview: string | undefined
    let changeSuffix = defaultSuffix

    for (const change of logItem.detail.changes || []) {
        if (!change?.field || !Object.hasOwn(mapping, change.field)) {
            continue
        }

        const processedChange = mapping[change.field](change, logItem)
        if (processedChange === null) {
            continue
        }

        const { description, summary, suffix, preview: changePreview } = processedChange
        descriptions.push(...(description ?? []))
        summaries.push(...(summary ?? description ?? []))
        preview = changePreview ?? preview
        if (suffix) {
            changeSuffix = suffix
        }
    }

    if (!descriptions.length) {
        return null
    }

    return {
        summary: activityLogSummary(logItem, <SentenceList listParts={summaries} />, target, preview),
        description: (
            <SentenceList
                listParts={descriptions}
                prefix={<ActivityLogUserName logItem={logItem} />}
                suffix={changeSuffix}
            />
        ),
    }
}
