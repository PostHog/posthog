import { LemonTag, Link } from '@posthog/lemon-ui'

import { lowercaseFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { EventType } from '~/types'

import { MetadataTag } from '../components/MetadataTag'
import { parseTagsCell } from '../generationTagRunsLogic'
import { asString } from '../utils'

export function TagDisplay({ eventProperties }: { eventProperties: EventType['properties'] }): JSX.Element {
    // Reuse the loader's JSON-string defense so a stringified $ai_tags property
    // doesn't end up iterated character-by-character here.
    const tags: string[] = parseTagsCell(eventProperties.$ai_tags)
    const reasoning = asString(eventProperties.$ai_tag_reasoning)
    const taggerName = asString(eventProperties.$ai_tagger_name)
    const model = asString(eventProperties.$ai_model)
    const traceId = asString(eventProperties.$ai_trace_id)
    const targetEventId = asString(eventProperties.$ai_target_event_id)
    const tagCount = eventProperties.$ai_tag_count

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
                {tags.length > 0 ? (
                    tags.map((tag: string) => (
                        <LemonTag key={tag} type="highlight">
                            {tag}
                        </LemonTag>
                    ))
                ) : (
                    <LemonTag type="muted">No tags</LemonTag>
                )}
            </div>

            <div className="flex flex-wrap gap-2">
                {taggerName && (
                    <MetadataTag label="Tagger" textToCopy={taggerName}>
                        {taggerName}
                    </MetadataTag>
                )}
                {model && (
                    <MetadataTag label="Model" textToCopy={lowercaseFirstLetter(model)}>
                        {lowercaseFirstLetter(model)}
                    </MetadataTag>
                )}
                {tagCount !== undefined && tagCount !== null && (
                    <MetadataTag label="Tag count">{String(tagCount)}</MetadataTag>
                )}
                {traceId && targetEventId && (
                    <MetadataTag label="Target event">
                        <Link to={urls.aiObservabilityTrace(traceId, { event: targetEventId })}>
                            {targetEventId.slice(0, 12)}...
                        </Link>
                    </MetadataTag>
                )}
            </div>

            {reasoning && (
                <div className="p-3 border rounded bg-surface-primary">
                    <div className="font-medium text-xs text-muted mb-1.5">REASONING</div>
                    <div className="text-sm whitespace-pre-wrap">{reasoning}</div>
                </div>
            )}
        </div>
    )
}
