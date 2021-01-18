import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { SaveOutlined } from '@ant-design/icons'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { Menu } from 'antd'
import { Link } from 'lib/components/Link'
import { toParams } from 'lib/utils'
import { router } from 'kea-router'
import { Drawer } from 'lib/components/Drawer'
import { SaveFilter } from 'scenes/sessions/filters/SaveFilter'

export function SavedFiltersMenu(): JSX.Element {
    const [saveVisible, setSaveVisible] = useState(false)

    const { activeFilter, savedFilters } = useValues(sessionsFiltersLogic)
    const { createSessionsFilter } = useActions(sessionsFiltersLogic)

    return (
        <>
            <Menu
                selectedKeys={activeFilter ? [activeFilter.id.toString()] : undefined}
                style={{ borderRight: 'none' }}
            >
                {savedFilters.map((savedFilter) => (
                    <Menu.Item key={savedFilter.id.toString()}>
                        <Link
                            to={`/sessions?${toParams({
                                ...router.values.searchParams,
                                filters: savedFilter.filters.properties,
                            })}`}
                            data-attr="sessions-filter-link"
                        >
                            {savedFilter.name}
                        </Link>
                    </Menu.Item>
                ))}

                <Menu.Divider />

                <Menu.Item key={'save'} disabled={!!activeFilter} onClick={() => setSaveVisible(true)}>
                    <span>
                        <SaveOutlined /> Save filters
                    </span>
                </Menu.Item>
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
