import { Dropdown, Menu } from 'antd'
import { IconArrowDropDown } from 'lib/components/icons'
import React from 'react'

export function InsightSaveButton({
    saveAs,
    saveInsight,
    isSaved,
}: {
    saveAs: () => void
    saveInsight: () => void
    isSaved: boolean | undefined
}): JSX.Element {
    const menu = (
        <Menu>
            <Menu.Item key="1" onClick={() => saveInsight({ setViewMode: true })}>
                Save
            </Menu.Item>
            <Menu.Item key="2" onClick={saveInsight}>
                Save and continue editing
            </Menu.Item>
            {isSaved && (
                <Menu.Item key="3" onClick={saveAs}>
                    Save as new insight
                </Menu.Item>
            )}
        </Menu>
    )
    return (
        <Dropdown.Button
            style={{ marginLeft: 8 }}
            type="primary"
            onClick={() => saveInsight({ setViewMode: true })}
            overlay={menu}
            icon={<IconArrowDropDown style={{ fontSize: 25 }} />}
        >
            Save
        </Dropdown.Button>
    )
}
