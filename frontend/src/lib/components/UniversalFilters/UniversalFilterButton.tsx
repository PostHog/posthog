import './UniversalFilterButton.scss'

import { IconFilter, IconX } from '@posthog/icons'
import { LemonButton, PopoverReferenceContext } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { midEllipsis } from 'lib/utils'
import React from 'react'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ActionFilter, AnyPropertyFilter } from '~/types'

import { EntityFilterInfo } from '../EntityFilterInfo'
import { formatPropertyLabel } from '../PropertyFilters/utils'
import { UniversalFilterValue } from './UniversalFilters'
import { isActionFilter, isEditableFilter, isEventFilter } from './utils'

export interface UniversalFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    children?: React.ReactNode
    filter: UniversalFilterValue
    disabledReason?: string
}

export const UniversalFilterButton = React.forwardRef<HTMLElement, UniversalFilterButtonProps>(
    function UniversalFilterButton({ onClick, onClose, filter }, ref): JSX.Element {
        const closable = onClose !== undefined

        const isEditable = isEditableFilter(filter)
        const isAction = isActionFilter(filter)
        const isEvent = isEventFilter(filter)

        const button = (
            <div
                ref={ref as any}
                onClick={isEditable ? onClick : undefined}
                className={clsx('UniversalFilterButton', {
                    'UniversalFilterButton--clickable': isEditable,
                    'UniversalFilterButton--closeable': closable,
                    'ph-no-capture': true,
                })}
            >
                {isEvent ? (
                    <EventLabel filter={filter} onClick={onClick} />
                ) : isAction ? (
                    <EntityFilterInfo filter={filter} />
                ) : (
                    <PropertyLabel filter={filter} />
                )}

                {closable && (
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

        return button
    }
)

const PropertyLabel = ({ filter }: { filter: AnyPropertyFilter }): JSX.Element => {
    const { cohortsById } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const label = formatPropertyLabel(
        filter,
        cohortsById,
        (s) => formatPropertyValueForDisplay(filter.key, s)?.toString() || '?'
    )

    return (
        <>
            <PropertyFilterIcon type={filter.type} />
            <span className="UniversalFilterButton-content" title={label}>
                {typeof label === 'string' ? midEllipsis(label, 32) : label}
            </span>
        </>
    )
}

const EventLabel = ({
    filter,
    onClick,
}: {
    filter: ActionFilter
    onClick: UniversalFilterButtonProps['onClick']
}): JSX.Element => {
    return (
        <div className="flex items-center space-x-1">
            <EntityFilterInfo filter={filter} />
            <LemonButton
                size="xsmall"
                icon={
                    <IconWithCount count={filter.properties?.length || 0} showZero={false}>
                        <IconFilter />
                    </IconWithCount>
                }
                className="p-0.5"
                onClick={onClick}
            />
        </div>
    )
}
