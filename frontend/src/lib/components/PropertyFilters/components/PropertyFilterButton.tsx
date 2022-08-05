import './PropertyFilterButton.scss'
import { Button } from 'antd'
import React from 'react'
import { AnyPropertyFilter } from '~/types'
import { CloseButton } from 'lib/components/CloseButton'
import { IconCohort, IconPerson, UnverifiedEvent } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { cohortsModel } from '~/models/cohortsModel'
import { useValues } from 'kea'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { formatPropertyLabel, midEllipsis } from 'lib/utils'
import { keyMapping } from 'lib/components/PropertyKeyInfo'

export interface PropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    children?: string
    item: AnyPropertyFilter
    style?: React.CSSProperties
}

function PropertyFilterIcon({ item }: { item: AnyPropertyFilter }): JSX.Element {
    let iconElement = <></>
    switch (item?.type) {
        case 'event':
            iconElement = (
                <Tooltip title={'Event property'}>
                    <UnverifiedEvent width={14} height={14} />
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

export const PropertyFilterButton = React.forwardRef<HTMLElement, PropertyFilterButtonProps>(
    function PropertyFilterButton({ onClick, onClose, children, item, style }, ref): JSX.Element {
        const { cohortsById } = useValues(cohortsModel)
        const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

        const label =
            children ||
            formatPropertyLabel(
                item,
                cohortsById,
                keyMapping,
                (s) => formatPropertyValueForDisplay(item.key, s)?.toString() || '?'
            )

        return (
            <Button
                shape="round"
                style={{ ...style }}
                onClick={onClick}
                ref={ref}
                className="PropertyFilterButton ph-no-capture"
            >
                <PropertyFilterIcon item={item} />
                <span className="PropertyFilterButton-content" title={label}>
                    {midEllipsis(label, 32)}
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
)
