import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { FilterOutlined, PlaySquareOutlined, UserOutlined } from '@ant-design/icons'
import { SavedFilter, sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { Menu } from 'antd'
import { Link } from 'lib/components/Link'
import { toParams } from 'lib/utils'
import { router } from 'kea-router'
import { Drawer } from 'lib/components/Drawer'
import { SaveFilter } from 'scenes/sessions/filters/SaveFilter'

const ICONS: Record<SavedFilter['id'], JSX.Element | undefined> = {
    all: <UserOutlined />,
    withrecordings: <PlaySquareOutlined />,
}

export function SavedFiltersMenu(): JSX.Element {
    const [saveVisible, setSaveVisible] = useState(false)

    const { activeFilter, savedFilters } = useValues(sessionsFiltersLogic)
    const { createSessionsFilter } = useActions(sessionsFiltersLogic)

    const globalFilters = savedFilters.filter(({ type }) => type === 'global')
    const customFilters = savedFilters.filter(({ type }) => type === 'custom')

    return (
        <>
            <Menu
                className="sessions-filters-menu"
                selectedKeys={activeFilter ? [activeFilter.id.toString()] : undefined}
            >
                <Menu.ItemGroup title="Filters">
                    {globalFilters.map((savedFilter) => (
                        <Menu.Item key={savedFilter.id.toString()}>
                            <MenuLink
                                key={savedFilter.id}
                                filter={savedFilter}
                                icon={ICONS[savedFilter.id] || <FilterOutlined />}
                            />
                        </Menu.Item>
                    ))}
                </Menu.ItemGroup>

                {customFilters.length > 0 && (
                    <Menu.ItemGroup title="Custom filters">
                        {customFilters.map((savedFilter) => (
                            <Menu.Item key={savedFilter.id.toString()}>
                                <MenuLink filter={savedFilter} icon={<FilterOutlined />} editable />
                            </Menu.Item>
                        ))}
                    </Menu.ItemGroup>
                )}
            </Menu>
            <Drawer
                title="Save session filters"
                onClose={() => setSaveVisible(false)}
                visible={saveVisible}
                destroyOnClose={true}
            >
                <SaveFilter
                    onSubmit={(name) => {
                        createSessionsFilter(name)
                        setSaveVisible(false)
                    }}
                />
            </Drawer>
        </>
    )
}

function MenuLink({ filter, icon }: { filter: SavedFilter; icon: JSX.Element; editable?: boolean }): JSX.Element {
    return (
        <Link
            to={`/sessions?${toParams({
                ...router.values.searchParams,
                filters: filter.filters.properties,
            })}`}
            data-attr="sessions-custom-filter-link"
        >
            {icon} {filter.name}
        </Link>
    )
}
