import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'
import { useState } from 'react'

import { NodeKind } from '~/queries/schema'

import { HogQLEditor } from '../HogQLEditor/HogQLEditor'

export const HogQLDropdown = ({
    hogQLValue,
    onHogQLValueChange,
    tableName,
}: {
    hogQLValue: string
    tableName: string
    onHogQLValueChange: (hogQLValue: string) => void
}): JSX.Element => {
    const [isHogQLDropdownVisible, setIsHogQLDropdownVisible] = useState(false)

    return (
        <div className="flex-auto overflow-hidden mt-2">
            <LemonDropdown
                visible={isHogQLDropdownVisible}
                closeOnClickInside={false}
                onClickOutside={() => setIsHogQLDropdownVisible(false)}
                overlay={
                    // eslint-disable-next-line react/forbid-dom-props
                    <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                        <HogQLEditor
                            value={hogQLValue}
                            metadataSource={{ kind: NodeKind.HogQLQuery, query: `SELECT * FROM ${tableName}` }}
                            onChange={(currentValue) => {
                                onHogQLValueChange(currentValue)
                                setIsHogQLDropdownVisible(false)
                            }}
                        />
                    </div>
                }
            >
                <LemonButton
                    fullWidth
                    type="secondary"
                    onClick={() => setIsHogQLDropdownVisible(!isHogQLDropdownVisible)}
                >
                    <code>{hogQLValue}</code>
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
