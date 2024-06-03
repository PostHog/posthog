import './UniversalFilterButton.scss'

import { IconFilter, IconX } from '@posthog/icons'
import { LemonButton, PopoverReferenceContext, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { midEllipsis } from 'lib/utils'
import React from 'react'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter } from '~/types'

import { EntityFilterInfo } from '../EntityFilterInfo'
import { formatPropertyLabel } from '../PropertyFilters/utils'
import { UniversalFilterValue } from './UniversalFilters'
import { isActionFilter } from './utils'

export interface PropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    children?: React.ReactNode
    item: UniversalFilterValue
    disabledReason?: string
}

export const UniversalFilterButton = React.forwardRef<HTMLElement, PropertyFilterButtonProps>(
    function PropertyFilterButton({ onClick, onClose, item, disabledReason }, ref): JSX.Element {
        const closable = onClose !== undefined

        const isEntity = isActionFilter(item)

        const button = (
            <div
                ref={ref as any}
                onClick={disabledReason || isEntity ? undefined : onClick}
                className={clsx('PropertyFilterButton PropertyFilterButton--clickable', {
                    'PropertyFilterButton--closeable': closable,
                    'ph-no-capture': true,
                })}
                aria-disabled={!!disabledReason}
            >
                {isEntity ? (
                    <div className="flex items-center space-x-1">
                        <EntityFilterInfo filter={item} />
                        <LemonButton
                            size="xsmall"
                            icon={
                                <IconWithCount count={item.properties?.length || 0} showZero={false}>
                                    <IconFilter />
                                </IconWithCount>
                            }
                            className="p-0.5"
                            onClick={disabledReason ? undefined : onClick}
                        />
                    </div>
                ) : (
                    <AnyPropertyLabel item={item} />
                )}

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
            </div>
        )

        if (disabledReason) {
            return <Tooltip title={disabledReason}>{button}</Tooltip>
        }

        return button
    }
)

const AnyPropertyLabel = ({ item }: { item: AnyPropertyFilter }): JSX.Element => {
    const { cohortsById } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const label = formatPropertyLabel(
        item,
        cohortsById,
        (s) => formatPropertyValueForDisplay(item.key, s)?.toString() || '?'
    )

    return (
        <>
            <PropertyFilterIcon type={item.type} />
            <span className="PropertyFilterButton-content" title={label}>
                {typeof label === 'string' ? midEllipsis(label, 32) : label}
            </span>
        </>
    )
}
