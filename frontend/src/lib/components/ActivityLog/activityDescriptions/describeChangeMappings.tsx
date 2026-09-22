import {
    ActivityLogItem,
    ActivityLogUserName,
    ChangeMapping,
    Description,
    ExpandedView,
    ExtendedDescription,
    HumanizedChange,
    activityLogSummary,
} from '../humanizeActivity'
import { SentenceList } from '../SentenceList'

export function describeChangeMappings(
    logItem: ActivityLogItem,
    mappings: ChangeMapping[],
    target: Description,
    defaultSuffix: Description,
    actor: JSX.Element = <ActivityLogUserName logItem={logItem} />
): HumanizedChange | null {
    const descriptions: Description[] = []
    const summaries: Description[] = []
    let preview: string | undefined
    let suffix = defaultSuffix
    let extendedDescription: ExtendedDescription
    let expandedView: ExpandedView | undefined

    for (const change of mappings) {
        descriptions.push(...(change.description ?? []))
        summaries.push(...(change.summary ?? change.description ?? []))
        preview = change.preview ?? preview
        suffix = change.suffix || suffix
        extendedDescription = change.extendedDescription || extendedDescription
        expandedView = change.expandedView || expandedView
    }

    if (!descriptions.length) {
        return null
    }

    return {
        summary: activityLogSummary(logItem, <SentenceList listParts={summaries} />, target, preview, actor),
        description: <SentenceList listParts={descriptions} prefix={actor} suffix={suffix} />,
        extendedDescription,
        expandedView,
    }
}
