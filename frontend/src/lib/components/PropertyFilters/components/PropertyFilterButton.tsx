import { Button } from 'antd'
import { useValues } from 'kea'
import { formatPropertyLabel, midEllipsis } from 'lib/utils'
import React from 'react'
import { cohortsModel } from '~/models/cohortsModel'
import { AnyPropertyFilter } from '~/types'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { CloseButton } from 'lib/components/CloseButton'
import { IconCohort, IconPerson, UnverifiedEventStack } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'

export interface PropertyFilterButtonProps {
    item: AnyPropertyFilter
    onClick?: () => void
    onClose?: () => void
    setRef?: (ref: HTMLElement) => void
    style?: React.CSSProperties
}

export function PropertyFilterText({ item }: PropertyFilterButtonProps): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const { formatForDisplay } = useValues(propertyDefinitionsModel)

    return (
        <>
            {formatPropertyLabel(item, cohortsById, keyMapping, (s) =>
                midEllipsis(formatForDisplay(item.key, s)?.toString() || '', 32)
            )}
        </>
    )
}

export function PropertyFilterButton({ item, ...props }: PropertyFilterButtonProps): JSX.Element {
    return (
        <FilterButton {...props} item={item}>
            <PropertyFilterText item={item} />
        </FilterButton>
    )
}

interface FilterRowProps {
    onClick?: () => void
    onClose?: () => void
    setRef?: (ref: HTMLElement) => void
    children: string | JSX.Element
    item: AnyPropertyFilter
    style?: React.CSSProperties
}

function PropertyFilterIcon({ item }: { item: AnyPropertyFilter }): JSX.Element {
    let iconElement = <></>
    switch (item?.type) {
        case 'event':
            iconElement = (
                <Tooltip title={'Event property'}>
                    <UnverifiedEventStack style={{ marginRight: '0.5em' }} width={'14'} height={'14'} />
                </Tooltip>
            )
            break
        case 'person':
            iconElement = (
                <Tooltip title={'Person property'}>
                    <IconPerson style={{ marginRight: '0.5em' }} />
                </Tooltip>
            )
            break
        case 'cohort':
            iconElement = (
                <Tooltip title={'Cohort filter'}>
                    <IconCohort style={{ marginRight: '0.5em' }} />
                </Tooltip>
            )
            break
    }
    return iconElement
}

export function FilterButton({ onClick, onClose, setRef, children, item, style }: FilterRowProps): JSX.Element {
    return (
        <Button
            type="primary"
            shape="round"
            style={{ overflow: 'hidden', ...style }}
            onClick={onClick}
            ref={setRef}
            className={'property-filter'}
        >
            <span
                className="ph-no-capture property-filter-button-label"
                style={{
                    width: '100%',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    display: 'flex',
                    alignItems: 'center',
                }}
            >
                <PropertyFilterIcon item={item} />
                {children}
                {onClose && (
                    <CloseButton
                        className={'ml-1'}
                        onClick={(e: MouseEvent) => {
                            e.stopPropagation()
                            onClose()
                        }}
                        style={{ cursor: 'pointer', float: 'none', marginLeft: 5 }}
                    />
                )}
            </span>
        </Button>
    )
}

export default PropertyFilterButton
