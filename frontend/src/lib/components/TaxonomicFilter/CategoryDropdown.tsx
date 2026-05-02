import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback } from 'react'

import { IconChevronDown } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import { CategoryDropdownVariant, TaxonomicFilterGroupType } from './types'

export function CategoryDropdown({
    variant,
    eventName,
    onAfterChange,
}: {
    variant: Exclude<CategoryDropdownVariant, 'control'>
    eventName?: string
    onAfterChange?: () => void
}): JSX.Element | null {
    const { activeTab, taxonomicGroups, taxonomicGroupTypes } = useValues(taxonomicFilterLogic)
    const { setActiveTab } = useActions(taxonomicFilterLogic)
    const { reportTaxonomicFilterCategorySelected } = useActions(eventUsageLogic)

    const onVisibilityChange = useCallback(
        (visible: boolean) => {
            if (visible) {
                posthog.capture('taxonomic filter category dropdown opened', {
                    variant,
                    [`$feature/${FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN}`]: variant,
                })
            }
        },
        [variant]
    )

    if (taxonomicGroupTypes.length <= 1) {
        return null
    }

    const openTab: TaxonomicFilterGroupType = activeTab ?? taxonomicGroupTypes[0]
    const activeGroup = taxonomicGroups.find((g) => g.type === openTab)
    const activeLabel = activeGroup?.name ?? openTab

    const items: LemonMenuItem[] = taxonomicGroupTypes.map((groupType) => {
        const group = taxonomicGroups.find((g) => g.type === groupType)
        return {
            key: groupType,
            label: group?.name ?? groupType,
            active: groupType === openTab,
            'data-attr': `taxonomic-category-dropdown-item-${groupType}`,
            onClick: () => {
                setActiveTab(groupType)
                reportTaxonomicFilterCategorySelected(groupType, eventName)
                onAfterChange?.()
            },
        }
    })

    const activeItemIndex = taxonomicGroupTypes.findIndex((g) => g === openTab)

    return (
        <LemonMenu
            items={items}
            onVisibilityChange={onVisibilityChange}
            activeItemIndex={activeItemIndex >= 0 ? activeItemIndex : undefined}
            placement="bottom-start"
            className="click-outside-block"
        >
            {renderTrigger(variant, activeLabel)}
        </LemonMenu>
    )
}

function renderTrigger(variant: Exclude<CategoryDropdownVariant, 'control'>, activeLabel: string): JSX.Element {
    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            sideIcon={<IconChevronDown />}
            data-attr={`taxonomic-category-dropdown-trigger-${variant}`}
            aria-label={`Current category: ${activeLabel}. Click to change.`}
        >
            {activeLabel}
        </LemonButton>
    )
}
