import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useState } from 'react'

import { NodeKind } from '~/queries/schema/schema-general'

import { HogQLEditor } from '../HogQLEditor/HogQLEditor'

export const HogQLDropdown = ({
    hogQLValue,
    onHogQLValueChange,
    tableName,
    hogQLEditorPlaceholder,
    className = '',
}: {
    hogQLValue: string
    tableName: string
    className?: string
    hogQLEditorPlaceholder?: string
    onHogQLValueChange: (hogQLValue: string) => void
}): JSX.Element => {
    const [isHogQLDropdownVisible, setIsHogQLDropdownVisible] = useState(false)

    return (
        <div className={clsx('flex-auto overflow-hidden', className)}>
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
                            placeholder={hogQLEditorPlaceholder}
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
