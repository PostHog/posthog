import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconChevronDown, IconPin, IconPinFilled } from '@posthog/icons'

import { CLICK_OUTSIDE_BLOCK_CLASS } from 'lib/hooks/useOutsideClickHandler'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { taxonomicFilterCategoryLayoutLogic } from './taxonomicFilterCategoryLayoutLogic'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import { TaxonomicFilterGroupType } from './types'

export function CategoryDropdown({
    eventName,
    onAfterChange,
    joinedToInput = false,
}: {
    eventName?: string
    onAfterChange?: () => void
    joinedToInput?: boolean
}): JSX.Element | null {
    const { activeTab, taxonomicGroups, taxonomicGroupTypes } = useValues(taxonomicFilterLogic)
    const { setActiveTab } = useActions(taxonomicFilterLogic)
    const { categoryRailPinned } = useValues(taxonomicFilterCategoryLayoutLogic)
    const { setCategoryRailPinned } = useActions(taxonomicFilterCategoryLayoutLogic)
    const { reportTaxonomicFilterCategorySelected } = useActions(eventUsageLogic)

    const onVisibilityChange = (visible: boolean): void => {
        if (visible) {
            posthog.capture('taxonomic filter category dropdown opened', {
                variant: 'pill',
            })
        }
    }

    if (taxonomicGroupTypes.length <= 1) {
        return null
    }

    const openTab: TaxonomicFilterGroupType = activeTab ?? taxonomicGroupTypes[0]
    const activeGroup = taxonomicGroups.find((g) => g.type === openTab)
    const activeLabel = activeGroup?.name ?? openTab

    const categoryItems: LemonMenuItem[] = taxonomicGroupTypes.map((groupType) => {
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

    const items: LemonMenuItems = [
        { items: categoryItems },
        {
            items: [
                {
                    key: 'toggle-category-rail',
                    label: categoryRailPinned ? 'Unpin categories' : 'Pin categories',
                    icon: categoryRailPinned ? <IconPinFilled /> : <IconPin />,
                    'data-attr': 'taxonomic-category-rail-toggle',
                    onClick: () => {
                        setCategoryRailPinned(!categoryRailPinned)
                        onAfterChange?.()
                    },
                },
            ],
        },
    ]

    const activeItemIndex = taxonomicGroupTypes.findIndex((g) => g === openTab)

    return (
        <LemonMenu
            items={items}
            onVisibilityChange={onVisibilityChange}
            activeItemIndex={activeItemIndex >= 0 ? activeItemIndex : undefined}
            placement="bottom-start"
            className={CLICK_OUTSIDE_BLOCK_CLASS}
        >
            {renderTrigger(activeLabel, joinedToInput, categoryRailPinned)}
        </LemonMenu>
    )
}

function renderTrigger(activeLabel: string, joinedToInput: boolean, categoryRailPinned: boolean): JSX.Element {
    return (
        <LemonButton
            type={joinedToInput ? 'tertiary' : 'secondary'}
            size="xsmall"
            truncate={joinedToInput}
            sideIcon={<IconChevronDown />}
            data-attr="taxonomic-category-dropdown-trigger"
            aria-label={`Current category: ${activeLabel}. Click to change.`}
            className={clsx(
                CLICK_OUTSIDE_BLOCK_CLASS,
                joinedToInput && 'TaxonomicFilter__category-dropdown',
                categoryRailPinned && 'hidden @max-[32rem]:inline-flex'
            )}
        >
            {activeLabel}
        </LemonButton>
    )
}
