import './UniversalFilterButton.scss'

import { IconFilter, IconLogomark, IconX } from '@posthog/icons'
import { LemonButton, PopoverReferenceContext } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { midEllipsis } from 'lib/utils'
import React from 'react'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ActionFilter, AnyPropertyFilter, FeaturePropertyFilter, UniversalFilterValue } from '~/types'

import { EntityFilterInfo } from '../EntityFilterInfo'
import { formatPropertyLabel } from '../PropertyFilters/utils'
import { isActionFilter, isEditableFilter, isEventFilter, isFeatureFlagFilter } from './utils'

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
        const isFeatureFlag = isFeatureFlagFilter(filter)
        const button = (
            <div
                ref={ref as any}
                onClick={isEditable ? onClick : undefined}
                className={clsx('UniversalFilterButton inline-flex items-center', {
                    'UniversalFilterButton--clickable': isEditable,
                    'UniversalFilterButton--closeable': closable,
                    'ph-no-capture': true,
                })}
            >
                <div className="flex items-center flex-1 truncate gap-1">
                    {isEvent ? (
                        <EventLabel filter={filter} onClick={onClick} />
                    ) : isAction ? (
                        <EntityFilterInfo filter={filter} />
                    ) : isFeatureFlag ? (
                        <FeatureFlagLabel filter={filter} />
                    ) : (
                        <PropertyLabel filter={filter} />
                    )}
                </div>

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

    let label = formatPropertyLabel(
        filter,
        cohortsById,
        (s) => formatPropertyValueForDisplay(filter.key, s)?.toString() || '?'
    )
    const isEventFeature = label.startsWith('$feature/')
    if (isEventFeature) {
        label = label.replace('$feature/', 'Feature: ')
    }

    return (
        <>
            {isEventFeature ? <IconLogomark /> : <PropertyFilterIcon type={filter.type} />}
            <span className="UniversalFilterButton-content flex flex-1 items-center truncate" title={label}>
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
        <div className="flex truncate  items-center space-x-1">
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

const FeatureFlagLabel = ({ filter }: { filter: FeaturePropertyFilter }): JSX.Element => {
    return <div className="flex items-center truncate">{filter.key}</div>
}
