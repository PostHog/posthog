import { ActivityChange, ActivityLogItem, ChangeMapping, Description, HumanizedChange } from '../humanizeActivity'
import { describeChangeMappings } from './describeChangeMappings'

export function describeMappedChanges(
    logItem: ActivityLogItem,
    mapping: Record<
        string,
        (change: ActivityChange, logItem: ActivityLogItem, asNotification?: boolean) => ChangeMapping | null
    >,
    target: Description,
    defaultSuffix: Description,
    asNotification?: boolean
): HumanizedChange | null {
    const mappings: ChangeMapping[] = []

    for (const change of logItem.detail.changes || []) {
        if (!change?.field || !Object.hasOwn(mapping, change.field)) {
            continue
        }

        const processedChange = mapping[change.field](change, logItem, asNotification)
        if (processedChange) {
            mappings.push(processedChange)
        }
    }

    return describeChangeMappings(logItem, mappings, target, defaultSuffix)
}
