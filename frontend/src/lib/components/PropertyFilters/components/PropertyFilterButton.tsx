import './PropertyFilterButton.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import React from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, PopoverReferenceContext, Tooltip } from '@posthog/lemon-ui'

import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { midEllipsis } from 'lib/utils'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter, GroupPropertyFilter, GroupTypeIndex } from '~/types'

import { formatPropertyLabel, propertyFilterTypeToPropertyDefinitionType } from '../utils'

export interface PropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    children?: string
    item: AnyPropertyFilter
    disabledReason?: string
}

export const PropertyFilterButton = React.forwardRef<HTMLElement, PropertyFilterButtonProps>(
    function PropertyFilterButton({ onClick, onClose, children, item, disabledReason }, ref): JSX.Element {
        const { cohortsById } = useValues(cohortsModel)
        const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

        const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(item.type)

        const closable = onClose !== undefined
        const clickable = onClick !== undefined
        const label =
            children ||
            formatPropertyLabel(
                item,
                cohortsById,
                (s) =>
                    formatPropertyValueForDisplay(
                        item.key,
                        s,
                        propertyDefinitionType,
                        (item as GroupPropertyFilter).group_type_index as GroupTypeIndex | undefined
                    )?.toString() || '?'
            )

        const ButtonComponent = clickable ? 'button' : 'div'

        const button = (
            <ButtonComponent
                ref={ref as any}
                onClick={disabledReason ? undefined : onClick}
                className={clsx('PropertyFilterButton', 'grow', {
                    'PropertyFilterButton--closeable': closable,
                    'PropertyFilterButton--clickable': clickable,
                    'ph-no-capture': true,
                })}
                aria-disabled={!!disabledReason}
                type={ButtonComponent === 'button' ? 'button' : undefined}
            >
                <PropertyFilterIcon type={item.type} />
                <span className="PropertyFilterButton-content" title={label}>
                    {midEllipsis(label, 32)}
                </span>
                {closable && !disabledReason && (
                    // The context below prevents close button from going into active status when filter popover is open
                    <PopoverReferenceContext.Provider value={null}>
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            onClick={(e) => {
                                e.stopPropagation()
                                onClose()
                            }}
                            className="p-0.5"
                        />
                    </PopoverReferenceContext.Provider>
                )}
            </ButtonComponent>
        )

        if (disabledReason) {
            return <Tooltip title={disabledReason}>{button}</Tooltip>
        }

        return button
    }
)
