import { forwardRef } from 'react'

import { Chip, ChipClose, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { midEllipsis } from 'lib/utils/strings'

import { GroupTypeIndex, PropertyFilterType } from '~/types'

import { GroupKeyFilterTooltip } from './GroupKeyFilterTooltip'

export interface QuillPropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    type?: PropertyFilterType
    label: string
    wraps: boolean
    showGroupCard: boolean
    groupTypeIndex: GroupTypeIndex | null | undefined
    groupKeys: string[]
    disabledReason?: string
}

export const QuillPropertyFilterButton = forwardRef<HTMLDivElement, QuillPropertyFilterButtonProps>(
    function QuillPropertyFilterButton(
        { onClick, onClose, type, label, wraps, showGroupCard, groupTypeIndex, groupKeys, disabledReason },
        ref
    ): JSX.Element {
        const chip = (
            <Chip
                ref={ref}
                size="default"
                nativeButton={false}
                onClick={disabledReason ? undefined : onClick}
                disabled={!!disabledReason}
                className={cn('ph-no-capture min-w-0 max-w-full', wraps && 'h-auto whitespace-normal')}
            >
                <PropertyFilterIcon type={type} />
                <span className="min-w-0 truncate" title={showGroupCard ? undefined : label}>
                    {wraps ? label : midEllipsis(label, 32)}
                </span>
                {onClose && !disabledReason ? (
                    <ChipClose
                        aria-label="Remove filter"
                        onClick={(e) => {
                            e.stopPropagation()
                            onClose()
                        }}
                    />
                ) : null}
            </Chip>
        )

        const tooltip = disabledReason ? (
            disabledReason
        ) : showGroupCard ? (
            <GroupKeyFilterTooltip
                groupTypeIndex={groupTypeIndex as GroupTypeIndex}
                groupKey={groupKeys[0]}
                fallbackLabel={label}
            />
        ) : null

        if (!tooltip) {
            return chip
        }
        return (
            <Tooltip>
                <TooltipTrigger render={chip} />
                <TooltipContent>{tooltip}</TooltipContent>
            </Tooltip>
        )
    }
)
