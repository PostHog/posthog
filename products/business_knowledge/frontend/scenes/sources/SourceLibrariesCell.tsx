import { useValues } from 'kea'

import { IconFolder } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { businessKnowledgeLogic } from './businessKnowledgeLogic'
import type { KnowledgeSource } from './businessKnowledgeLogic'

const VISIBLE_TAGS = 2

export function SourceLibrariesCell({ source }: { source: KnowledgeSource }): JSX.Element {
    const { libraryNamesById } = useValues(businessKnowledgeLogic)
    const names = source.library_ids.map((id) => libraryNamesById[id]).filter((name): name is string => !!name)

    if (names.length === 0) {
        return <span className="text-secondary">None</span>
    }

    const hidden = names.slice(VISIBLE_TAGS)
    return (
        <div className="flex flex-wrap gap-1">
            {names.slice(0, VISIBLE_TAGS).map((name) => (
                <LemonTag key={name} icon={<IconFolder />} className="max-w-40">
                    <span className="truncate">{name}</span>
                </LemonTag>
            ))}
            {hidden.length > 0 && <LemonTag title={hidden.join(', ')}>+{hidden.length}</LemonTag>}
        </div>
    )
}
