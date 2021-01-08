import React, { useState } from 'react'
import { useValues } from 'kea'
import { SaveOutlined } from '@ant-design/icons'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { Button, Dropdown, Menu } from 'antd'
import { Link } from 'lib/components/Link'
import { toParams } from 'lib/utils'
import { router } from 'kea-router'
import { Drawer } from 'lib/components/Drawer'
import { SaveFilter } from 'scenes/sessions/filters/SaveFilter'

export function SavedFiltersDropdown(): JSX.Element {
    const [saveVisible, setSaveVisible] = useState(false)

    const { activeFilter, savedFilters } = useValues(sessionsFiltersLogic)

    return (
        <>
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

                        <Menu.Divider />

                        <Menu.Item key={'save'} disabled={!!activeFilter} onClick={() => setSaveVisible(true)}>
                            <span>
                                <SaveOutlined /> Save filters
                            </span>
                        </Menu.Item>
                    </Menu>
                }
                placement="bottomLeft"
            >
                <Button>{activeFilter ? activeFilter.name : 'Custom filter'}</Button>
            </Dropdown>
            <Drawer
                title="Save session filters"
                onClose={() => setSaveVisible(false)}
                visible={saveVisible}
                destroyOnClose={true}
            >
                <SaveFilter />
            </Drawer>
        </>
    )
}
