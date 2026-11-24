import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { Text } from '@posthog/quill'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'
import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'

import { TodayPaneGroupLabel } from './TodayPaneGroupLabel'
import { todayShellLogic } from './todayShellLogic'
import { WarehouseItem, visibleWarehouseItems } from './todayWarehouseItems'

// pinned: the data-attr values and analytics event name in this file feed autocapture and dashboards, so renaming them breaks both.

const GROUP_ORDER: WarehouseItem['group'][] = ['home', 'data', 'models', 'data_catalog', 'manage']

const GROUP_HEADINGS: Partial<Record<WarehouseItem['group'], string>> = {
    data: 'Data',
    models: 'Models',
    data_catalog: 'Data catalog',
    manage: 'Manage',
}

/** The warehouse pane's navigation: every warehouse page, grouped. */
export function TodayWarehouseSidebar(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentWarehouseItem: current } = useValues(todayShellLogic)
    const [search, setSearch] = useState('')

    const term = search.trim().toLowerCase()
    const items = visibleWarehouseItems(featureFlags).filter(
        (item) =>
            !term ||
            item.label.toLowerCase().includes(term) ||
            (GROUP_HEADINGS[item.group] ?? '').toLowerCase().includes(term)
    )
    const groups = GROUP_ORDER.map((group) => items.filter((item) => item.group === group)).filter(
        (group) => group.length
    )

    return (
        <div className="TodayPane group/colorful-product-icons colorful-product-icons-true" data-quill>
            <SidebarSearchList
                query={search}
                onQueryChange={setSearch}
                searchLabel="Search warehouse"
                dataAttr="today-warehouse-search"
            >
                {groups.length === 0 && (
                    <Text size="xs" variant="muted" className="block px-2 py-1">
                        Nothing in the warehouse matches that search.
                    </Text>
                )}
                {groups.map((group, index) => (
                    <div key={group[0].group}>
                        {GROUP_HEADINGS[group[0].group] ? (
                            <TodayPaneGroupLabel first={index === 0}>
                                {GROUP_HEADINGS[group[0].group]}
                            </TodayPaneGroupLabel>
                        ) : (
                            index > 0 && <div className="h-2" />
                        )}
                        {group.map((item) => (
                            <SidebarRow
                                key={item.key}
                                value={`warehouse:${item.key}`}
                                label={item.label}
                                icon={iconForType(item.iconType)}
                                to={item.href}
                                active={item.key === current?.key}
                                onClick={() =>
                                    posthog.capture('warehouse menu item clicked', {
                                        item: item.key,
                                        from: current?.key ?? null,
                                    })
                                }
                                dataAttr={`today-warehouse-menu-${item.key}`}
                            />
                        ))}
                    </div>
                ))}
            </SidebarSearchList>
        </div>
    )
}
