import './PropertyFilterButton.scss'

import clsx from 'clsx'
import React from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, PopoverReferenceContext, Tooltip } from '@posthog/lemon-ui'

import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { midEllipsis } from 'lib/utils/strings'

import { GroupTypeIndex, PropertyFilterType } from '~/types'

import { GroupKeyFilterTooltip } from './GroupKeyFilterTooltip'

export interface LemonPropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    item: { type?: PropertyFilterType }
    label: string
    wraps: boolean
    showGroupCard: boolean
    groupTypeIndex: GroupTypeIndex | null | undefined
    groupKeys: string[]
    disabledReason?: string
    compact?: boolean
}

export const LemonPropertyFilterButton = React.forwardRef<HTMLElement, LemonPropertyFilterButtonProps>(
    function LemonPropertyFilterButton(
        { onClick, onClose, item, label, wraps, showGroupCard, groupTypeIndex, groupKeys, disabledReason, compact },
        ref
    ): JSX.Element {
        const closable = onClose !== undefined
        const clickable = onClick !== undefined

        // A native <button> can't contain the nested close <button> (invalid DOM nesting),
        // so a closeable chip renders as a div with button semantics instead
        const ButtonComponent = clickable && !closable ? 'button' : 'div'
        const buttonRoleProps =
            clickable && ButtonComponent === 'div'
                ? {
                      role: 'button',
                      tabIndex: 0,
                      onKeyDown: (e: React.KeyboardEvent) => {
                          if (!disabledReason && (e.key === 'Enter' || e.key === ' ')) {
                              e.preventDefault()
                              onClick?.()
                          }
                      },
                  }
                : {}

        const button = (
            <ButtonComponent
                ref={ref as any}
                onClick={disabledReason ? undefined : onClick}
                className={clsx('PropertyFilterButton', 'grow', 'ph-no-capture', {
                    'PropertyFilterButton--closeable': closable,
                    'PropertyFilterButton--clickable': clickable,
                    'PropertyFilterButton--compact': compact,
                    'PropertyFilterButton--wraps': wraps,
                })}
                aria-disabled={!!disabledReason}
                type={ButtonComponent === 'button' ? 'button' : undefined}
                {...buttonRoleProps}
            >
                <PropertyFilterIcon type={item.type} />
                <span className="PropertyFilterButton-content" title={showGroupCard ? undefined : label}>
                    {wraps ? label : midEllipsis(label, 32)}
                </span>
                {closable &&
                    !disabledReason && (
                        // The context below prevents close button from going into active status when filter popover is open
                        <PopoverReferenceContext.Provider value={null}>
                            <LemonButton
                                size="xsmall"
                                icon={<IconX />}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    onClose()
                                }}
                                className="p-0.5"
                            />
                        </PopoverReferenceContext.Provider>
                    )}
            </ButtonComponent>
        )

        if (disabledReason) {
            return <Tooltip title={disabledReason}>{button}</Tooltip>
        }

        if (showGroupCard) {
            return (
                <Tooltip
                    interactive
                    title={
                        <GroupKeyFilterTooltip
                            groupTypeIndex={groupTypeIndex as GroupTypeIndex}
                            groupKey={groupKeys[0]}
                            fallbackLabel={label}
                        />
                    }
                >
                    {button}
                </Tooltip>
            )
        }

        return button
    }
)
