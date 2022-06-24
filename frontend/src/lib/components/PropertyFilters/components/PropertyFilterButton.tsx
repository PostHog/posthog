import './PropertyFilterButton.scss'
import { Button } from 'antd'
import { useValues } from 'kea'
import { formatPropertyLabel, midEllipsis } from 'lib/utils'
import React, { MutableRefObject } from 'react'
import { cohortsModel } from '~/models/cohortsModel'
import { AnyPropertyFilter } from '~/types'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { CloseButton } from 'lib/components/CloseButton'
import { IconCohort, IconPerson, UnverifiedEventStack } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'

export interface PropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    ref?: MutableRefObject<HTMLElement | null>
    children?: string | JSX.Element
    item: AnyPropertyFilter
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

function PropertyFilterIcon({ item }: { item: AnyPropertyFilter }): JSX.Element {
    let iconElement = <></>
    switch (item?.type) {
        case 'event':
            iconElement = (
                <Tooltip title={'Event property'}>
                    <UnverifiedEventStack width={'14'} height={'14'} />
                </Tooltip>
            )
            break
        case 'person':
            iconElement = (
                <Tooltip title={'Person property'}>
                    <IconPerson />
                </Tooltip>
            )
            break
        case 'cohort':
            iconElement = (
                <Tooltip title={'Cohort filter'}>
                    <IconCohort />
                </Tooltip>
            )
            break
    }
    return iconElement
}

export function PropertyFilterButton({
    onClick,
    onClose,
    ref,
    children,
    item,
    style,
}: PropertyFilterButtonProps): JSX.Element {
    return (
        <Button
            shape="round"
            style={{ ...style }}
            onClick={onClick}
            ref={ref}
            className="PropertyFilterButton ph-no-capture"
        >
            <PropertyFilterIcon item={item} />
            <span className="PropertyFilterButton-content">
                {children ? children : <PropertyFilterText item={item} />}
            </span>
            {onClose && (
                <CloseButton
                    onClick={(e: MouseEvent) => {
                        e.stopPropagation()
                        onClose()
                    }}
                />
            )}
        </Button>
    )
}
