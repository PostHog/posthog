import clsx from 'clsx'
import type { ReactNode } from 'react'
import { useState } from 'react'

import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { NodeKind } from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier } from '~/queries/utils'

import { HogQLEditor } from '../HogQLEditor/HogQLEditor'

export const HogQLDropdown = ({
    hogQLValue,
    onHogQLValueChange,
    tableName,
    hogQLEditorPlaceholder,
    className = '',
    size,
    connectionId,
    buttonIcon,
    buttonLabel,
    buttonTooltip,
    buttonAriaLabel,
    visible,
    onVisibilityChange,
}: {
    hogQLValue: string
    tableName: string
    connectionId?: string
    className?: string
    hogQLEditorPlaceholder?: string
    size?: 'small' | 'medium'
    buttonIcon?: JSX.Element
    buttonLabel?: ReactNode
    buttonTooltip?: string
    buttonAriaLabel?: string
    visible?: boolean
    onVisibilityChange?: (visible: boolean) => void
    onHogQLValueChange: (hogQLValue: string) => void
}): JSX.Element => {
    const [internalVisibility, setInternalVisibility] = useState(false)
    const isHogQLDropdownVisible = visible ?? internalVisibility
    const setIsHogQLDropdownVisible = (nextVisibility: boolean): void => {
        setInternalVisibility(nextVisibility)
        onVisibilityChange?.(nextVisibility)
    }

    return (
        <div className={clsx('flex-auto min-w-0', className)}>
            <LemonDropdown
                visible={isHogQLDropdownVisible}
                closeOnClickInside={false}
                onClickOutside={() => setIsHogQLDropdownVisible(false)}
                overlay={
                    // eslint-disable-next-line react/forbid-dom-props
                    <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                        <HogQLEditor
                            value={hogQLValue}
                            metadataSource={{
                                kind: NodeKind.HogQLQuery,
                                query: `SELECT * FROM ${escapeDottedHogQLIdentifier(tableName)}`,
                                connectionId,
                            }}
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
                    size={size}
                    icon={buttonIcon}
                    tooltip={buttonTooltip}
                    aria-label={buttonAriaLabel}
                    onClick={() => setIsHogQLDropdownVisible(!isHogQLDropdownVisible)}
                >
                    {buttonLabel ?? <code>{hogQLValue}</code>}
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
