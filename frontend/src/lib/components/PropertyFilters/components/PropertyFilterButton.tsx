import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { fullNameOrEmail } from 'lib/utils/strings'
import { membersLogic } from 'scenes/organization/membersLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter, GroupPropertyFilter, GroupTypeIndex } from '~/types'

import {
    formatPropertyLabel,
    isAccountRelationshipPropertyFilter,
    isBehavioralPropertyFilter,
    isGroupCardFilterKey,
    propertyFilterTypeToPropertyDefinitionType,
} from '../utils'
import { LemonPropertyFilterButton } from './LemonPropertyFilterButton'
import { QuillPropertyFilterButton } from './QuillPropertyFilterButton'

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
        const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
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

        const groupTypeIndex = (item as GroupPropertyFilter).group_type_index as GroupTypeIndex | null | undefined
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

        const sharedProps = {
            onClick,
            onClose,
            label,
            wraps,
            showGroupCard,
            groupTypeIndex,
            groupKeys,
            disabledReason,
        }
        return quillEnabled ? (
            <QuillPropertyFilterButton ref={ref as React.Ref<HTMLDivElement>} type={item.type} {...sharedProps} />
        ) : (
            <LemonPropertyFilterButton ref={ref} item={item} compact={compact} {...sharedProps} />
        )
    }
)
