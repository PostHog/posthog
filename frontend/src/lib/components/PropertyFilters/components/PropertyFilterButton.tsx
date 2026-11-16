import './PropertyFilterButton.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, PopoverReferenceContext, Tooltip } from '@posthog/lemon-ui'

import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { fullNameOrEmail, midEllipsis } from 'lib/utils/strings'

import { cohortsModel } from '~/models/cohortsModel'
import { membersLogic } from '~/models/membersLogic'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter, GroupPropertyFilter, GroupTypeIndex } from '~/types'

import {
    formatPropertyLabel,
    isAccountRelationshipPropertyFilter,
    isBehavioralPropertyFilter,
    isGroupCardFilterKey,
    isHogQLPropertyFilter,
    propertyFilterTypeToPropertyDefinitionType,
} from '../utils'
import { GroupKeyFilterTooltip } from './GroupKeyFilterTooltip'
import { type PropertyFilterTriggerProps, QuillPropertyFilterButton } from './QuillPropertyFilterButton'

export interface PropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    children?: string
    item: AnyPropertyFilter
    disabledReason?: string
    compact?: boolean
    /** Props from a quill popover trigger, applied to the pill's main button */
    triggerProps?: PropertyFilterTriggerProps
}

export const PropertyFilterButton = React.forwardRef<HTMLElement, PropertyFilterButtonProps>(
    function PropertyFilterButton(
        { onClick, onClose, children, item, disabledReason, compact = false, triggerProps },
        ref
    ): JSX.Element {
        const quillSurface = useQuillSurface()
        const { cohortsById } = useValues(cohortsModel)
        const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

        const { meFirstMembers } = useValues(membersLogic)
        const { ensureAllMembersLoaded } = useActions(membersLogic)
        useEffect(() => {
            if (isAccountRelationshipPropertyFilter(item)) {
                ensureAllMembersLoaded()
            }
        }, [item.type, ensureAllMembersLoaded])

        const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(item.type)

        // A behavioral label is a whole sentence, which mid-ellipsis would turn into nonsense
        const wraps = isBehavioralPropertyFilter(item)

        const label =
            children ||
            formatPropertyLabel(item, cohortsById, (s) => {
                if (isAccountRelationshipPropertyFilter(item)) {
                    return (Array.isArray(s) ? s : [s])
                        .map((id) => {
                            const member = meFirstMembers.find(({ user }) => String(user.id) === String(id))
                            return member ? fullNameOrEmail(member.user) : String(id)
                        })
                        .join(', ')
                }
                return (
                    formatPropertyValueForDisplay(
                        item.key,
                        s,
                        propertyDefinitionType,
                        (item as GroupPropertyFilter).group_type_index as GroupTypeIndex | undefined
                    )?.toString() || '?'
                )
            })

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

        const fullLabel = !children && isHogQLPropertyFilter(item) ? item.key : label
        const groupCard = showGroupCard ? (
            <GroupKeyFilterTooltip
                groupTypeIndex={groupTypeIndex as GroupTypeIndex}
                groupKey={groupKeys[0]}
                fallbackLabel={label}
            />
        ) : null
        const displayLabel = wraps ? label : midEllipsis(label, 32)

        if (quillSurface) {
            return (
                <QuillPropertyFilterButton
                    ref={ref}
                    icon={<PropertyFilterIcon type={item.type} />}
                    displayLabel={displayLabel}
                    wraps={wraps}
                    tooltip={
                        groupCard ??
                        (displayLabel !== fullLabel ? <span className="ph-no-capture">{fullLabel}</span> : undefined)
                    }
                    onClick={onClick}
                    onClose={onClose}
                    disabledReason={disabledReason}
                    triggerProps={triggerProps}
                />
            )
        }

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
                <span className="PropertyFilterButton-content" title={showGroupCard ? undefined : fullLabel}>
                    {displayLabel}
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
                <Tooltip interactive title={groupCard}>
                    {button}
                </Tooltip>
            )
        }

        return button
    }
)
