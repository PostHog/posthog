import { useEffect, useRef } from 'react'

import { IconInfo, IconX } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils'
import { compareInsightTopLevelSections } from 'scenes/insights/utils'

import { Node } from '~/queries/schema/schema-general'

export interface SuggestionBannerProps {
    previousQuery: Node
    suggestedQuery: Node | null
    onReject: () => void
}

export function SuggestionBanner({ previousQuery, suggestedQuery, onReject }: SuggestionBannerProps): JSX.Element {
    const ref = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (ref.current) {
            ref.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
    }, [previousQuery])

    const changedLabels = compareInsightTopLevelSections(previousQuery, suggestedQuery)
    const diffString = `🔍 ${pluralize(changedLabels.length, 'section')} changed: \n${changedLabels.join('\n')}`

    return (
        <div className="w-full px-2" ref={ref}>
            <div className="bg-surface-tertiary/80 w-full flex justify-between items-center p-1 pl-2 mx-auto rounded-bl rounded-br">
                <div className="text-sm text-muted flex items-center gap-2 no-wrap">
                    <span className="size-2 bg-accent-active rounded-full" />
                    <div className="flex items-center gap-1">
                        <span>{pluralize(changedLabels.length, 'change')}</span>
                        {changedLabels.length > 0 && (
                            <Tooltip title={<div className="whitespace-pre-line">{diffString}</div>}>
                                <IconInfo className="text-sm text-muted cursor-help" />
                            </Tooltip>
                        )}
                    </div>
                </div>

                <LemonButton status="danger" onClick={onReject} tooltipPlacement="top" size="small" icon={<IconX />}>
                    Reject changes
                </LemonButton>
            </div>
        </div>
    )
}
