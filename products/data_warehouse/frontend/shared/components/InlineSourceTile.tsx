import { LemonTag } from '@posthog/lemon-ui'

import type { ExternalDataSourceType } from '~/types'

import { SourceIcon } from './SourceIcon'

export interface InlineSourceItem {
    id: ExternalDataSourceType
    label: string
    detected: boolean
}

export function InlineSourceTile({
    source,
    onSelect,
}: {
    source: InlineSourceItem
    onSelect: (sourceId: ExternalDataSourceType) => void
}): JSX.Element {
    return (
        <button
            type="button"
            className="flex items-center gap-3 p-3 rounded-lg border border-border bg-bg-light cursor-pointer text-left"
            onClick={() => onSelect(source.id)}
            data-attr={source.detected ? 'inline-source-detected' : undefined}
        >
            <SourceIcon type={source.id} size="small" disableTooltip />
            <span className="flex min-w-0 flex-col items-start gap-1">
                <span className="font-medium text-sm">{source.label}</span>
                {source.detected && (
                    <LemonTag type="success" size="small">
                        Found in your code
                    </LemonTag>
                )}
            </span>
        </button>
    )
}
