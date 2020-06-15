import React from 'react'
import { Button } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { elementsLogic } from '../elements/elementsLogic'
import { ActionStep } from '~/toolbar/elements/ActionStep'

export function InspectElement() {
    const { disableInspect, enableInspect } = useActions(elementsLogic)
    const { inspectEnabled, selectedElementMeta } = useValues(elementsLogic)

    return (
        <div className="toolbar-block">
            <div>
                <Button
                    type={inspectEnabled ? 'primary' : 'secondary'}
                    onClick={inspectEnabled ? disableInspect : enableInspect}
                >
                    <SearchOutlined /> Select an element
                </Button>
            </div>
            {selectedElementMeta ? (
                <div style={{ marginTop: 10 }}>
                    <ActionStep actionStep={selectedElementMeta.actionStep} />
                </div>
            ) : null}
        </div>
    )
}
