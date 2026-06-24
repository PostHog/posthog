import './PropertyFilterButton.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import React from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, PopoverReferenceContext, Tooltip } from '@posthog/lemon-ui'

import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { midEllipsis } from 'lib/utils/strings'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter, GroupPropertyFilter, GroupTypeIndex } from '~/types'

import { formatPropertyLabel, isGroupCardFilterKey, propertyFilterTypeToPropertyDefinitionType } from '../utils'
import { GroupKeyFilterTooltip } from './GroupKeyFilterTooltip'

export interface PropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    children?: string
    item: AnyPropertyFilter
    disabledReason?: string
    compact?: boolean
}

export const PropertyFilterButton = React.forwardRef<HTMLElement, PropertyFilterButtonProps>(
    function PropertyFilterButton(
        { onClick, onClose, children, item, disabledReason, compact = false },
        ref
    ): JSX.Element {
        const { cohortsById } = useValues(cohortsModel)
        const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

        const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(item.type)

        const label =
            children ||
            formatPropertyLabel(
                item,
                cohortsById,
                (s) =>
                    formatPropertyValueForDisplay(
                        item.key,
                        s,
                        propertyDefinitionType,
                        (item as GroupPropertyFilter).group_type_index as GroupTypeIndex | undefined
                    )?.toString() || '?'
            )

        // Don't render empty buttons
        if (!label) {
            return <></>
        }

        const groupTypeIndex = (item as GroupPropertyFilter).group_type_index
        const groupKeys = Array.isArray(item.value)
            ? item.value.map(String)
            : item.value !== null && item.value !== undefined
              ? [String(item.value)]
              : []
        // When a single-group filter's value resolves to a real group we replace
        // the bare "<key> = <uuid>" tooltip with a formatted card so the user can
        // confirm they picked the right group (e.g. after pasting a UUID). This is
        // display only and falls back to the label when the value isn't a real
        // group key. Restricted to a single value so hovering only ever looks up
        // the one group under the mouse — never a fan-out across an "is one of" list.
        const showGroupCard =
            isGroupCardFilterKey(item.key, item.type) &&
            groupTypeIndex !== null &&
            groupTypeIndex !== undefined &&
            groupKeys.length === 1

        const closable = onClose !== undefined
        const clickable = onClick !== undefined

        const ButtonComponent = clickable ? 'button' : 'div'

        const button = (
            <ButtonComponent
                ref={ref as any}
                onClick={disabledReason ? undefined : onClick}
                className={clsx('PropertyFilterButton', 'grow', 'ph-no-capture', {
                    'PropertyFilterButton--closeable': closable,
                    'PropertyFilterButton--clickable': clickable,
                    'PropertyFilterButton--compact': compact,
                })}
                aria-disabled={!!disabledReason}
                type={ButtonComponent === 'button' ? 'button' : undefined}
            >
                <PropertyFilterIcon type={item.type} />
                <span className="PropertyFilterButton-content" title={showGroupCard ? undefined : label}>
                    {midEllipsis(label, 32)}
                </span>
                {closable && !disabledReason && (
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
