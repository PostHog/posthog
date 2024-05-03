import './PropertyFilterButton.scss'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { midEllipsis } from 'lib/utils'
import React from 'react'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter } from '~/types'

import { formatPropertyLabel } from '../utils'

export interface PropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    children?: string
    item: AnyPropertyFilter
    disabled?: boolean
}

export const PropertyFilterButton = React.forwardRef<HTMLElement, PropertyFilterButtonProps>(
    function PropertyFilterButton({ onClick, onClose, children, item, disabled }, ref): JSX.Element {
        const { cohortsById } = useValues(cohortsModel)
        const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

        const closable = onClose !== undefined
        const clickable = onClick !== undefined
        const label =
            children ||
            formatPropertyLabel(item, cohortsById, (s) => formatPropertyValueForDisplay(item.key, s)?.toString() || '?')

        const ButtonComponent = clickable ? 'button' : 'div'

        return (
            <ButtonComponent
                ref={ref as any}
                onClick={disabled ? undefined : onClick}
                className={clsx('PropertyFilterButton', {
                    'PropertyFilterButton--closeable': closable,
                    'PropertyFilterButton--clickable': clickable,
                    'ph-no-capture': true,
                })}
                aria-disabled={disabled}
            >
                <PropertyFilterIcon type={item.type} />
                <span className="PropertyFilterButton-content" title={label}>
                    {midEllipsis(label, 32)}
                </span>
                {closable && !disabled && (
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        onClick={(e) => {
                            e.stopPropagation()
                            onClose()
                        }}
                        className="p-0.5"
                    />
                )}
            </ButtonComponent>
        )
    }
)
