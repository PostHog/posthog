import React from 'react'
import { useValues } from 'kea'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { Button, Dropdown, Menu } from 'antd'
import { Link } from 'lib/components/Link'
import { toParams } from 'lib/utils'
import { router } from 'kea-router'

export function SavedFiltersDropdown(): JSX.Element {
    const { activeFilter, savedFilters } = useValues(sessionsFiltersLogic)

    return (
        <Dropdown
            overlay={
                <Menu selectedKeys={activeFilter ? [activeFilter.id] : undefined}>
                    {savedFilters.map((savedFilter) => (
                        <Menu.Item key={savedFilter.id}>
                            <Link
                                to={`/sessions?${toParams({
                                    ...router.values.searchParams,
                                    filters: savedFilter.filters,
                                })}`}
                            >
                                {savedFilter.name}
                            </Link>
                        </Menu.Item>
                    ))}
                </Menu>
            }
            placement="bottomLeft"
        >
            <Button>{activeFilter ? activeFilter.name : 'Custom filter'}</Button>
        </Dropdown>
    )
}
