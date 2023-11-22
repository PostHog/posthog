import './PropertyFilterButton.scss'

import { Button } from 'antd'
import { useValues } from 'kea'
import { CloseButton } from 'lib/components/CloseButton'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { KEY_MAPPING } from 'lib/taxonomy'
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
    style?: React.CSSProperties
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
                KEY_MAPPING,
                (s) => formatPropertyValueForDisplay(item.key, s)?.toString() || '?'
            )

        return (
            <Button
                shape="round"
                style={style}
                onClick={onClick}
                ref={ref}
                className="PropertyFilterButton ph-no-capture"
            >
                <PropertyFilterIcon type={item.type} />
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
