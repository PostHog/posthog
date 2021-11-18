import { Button, Dropdown, Menu } from 'antd'
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
            <Menu.Item key="1" onClick={saveInsight}>
                Save
            </Menu.Item>
            <Menu.Item key="3" onClick={saveAs} data-attr="insight-save-as-new-insight">
                Save as new insight
            </Menu.Item>
        </Menu>
    )
    return isSaved ? (
        <Dropdown.Button
            style={{ marginLeft: 8 }}
            type="primary"
            onClick={saveInsight}
            overlay={menu}
            data-attr="insight-save-button"
            icon={<IconArrowDropDown data-attr="insight-save-dropdown" style={{ fontSize: 25 }} />}
        >
            Save
        </Dropdown.Button>
    ) : (
        <Button style={{ marginLeft: 8 }} type="primary" onClick={saveInsight} data-attr="insight-save-button">
            Save
        </Button>
    )
}
