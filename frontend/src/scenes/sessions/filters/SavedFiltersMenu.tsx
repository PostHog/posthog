import React from 'react'
import { useActions, useValues } from 'kea'
import { FilterOutlined, PlaySquareOutlined, UserOutlined, EditOutlined, EyeInvisibleOutlined } from '@ant-design/icons'
import { SavedFilter, sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { Button, Menu, Skeleton } from 'antd'
import { Link } from 'lib/components/Link'
import { toParams } from 'lib/utils'
import { router } from 'kea-router'
import { Drawer } from 'lib/components/Drawer'
import { SaveFilter } from 'scenes/sessions/filters/SaveFilter'

const ICONS: Record<SavedFilter['id'], JSX.Element | undefined> = {
    all: <UserOutlined />,
    withrecordings: <PlaySquareOutlined />,
    unseen: <EyeInvisibleOutlined />,
}

export function SavedFiltersMenu(): JSX.Element {
    const { activeFilter, savedFilters, editedFilter, customFiltersLoading } = useValues(sessionsFiltersLogic)
    const { closeEditFilter } = useActions(sessionsFiltersLogic)

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

                {customFiltersLoading ? (
                    <Skeleton paragraph={{ rows: 1 }} active />
                ) : (
                    customFilters.length > 0 && (
                        <Menu.ItemGroup title="Custom filters">
                            {customFilters.map((savedFilter) => (
                                <Menu.Item key={savedFilter.id.toString()}>
                                    <MenuLink filter={savedFilter} icon={<FilterOutlined />} editable />
                                </Menu.Item>
                            ))}
                        </Menu.ItemGroup>
                    )
                )}
            </Menu>
            {!!editedFilter && (
                <Drawer
                    title={editedFilter.id !== null ? 'Update filters' : 'Save filters'}
                    onClose={closeEditFilter}
                    visible={!!editedFilter}
                    destroyOnClose={true}
                >
                    <SaveFilter filter={editedFilter} />
                </Drawer>
            )}
        </>
    )
}

function MenuLink({
    filter,
    icon,
    editable,
}: {
    filter: SavedFilter
    icon: JSX.Element
    editable?: boolean
}): JSX.Element {
    const { openEditFilter } = useActions(sessionsFiltersLogic)

    const handleEdit = (event: React.MouseEvent): void => {
        event.stopPropagation()
        event.preventDefault()
        openEditFilter(filter)
    }

    return (
        <Link
            to={`/sessions?${toParams({
                ...router.values.searchParams,
                filters: filter.filters.properties,
            })}`}
            data-attr="sessions-filter-link"
        >
            <span>
                {icon} {filter.name}
            </span>
            {editable && <Button onClick={handleEdit} icon={<EditOutlined />} className="edit-filter-button" />}
        </Link>
    )
}
