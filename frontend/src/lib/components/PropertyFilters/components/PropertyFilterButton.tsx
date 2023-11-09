import './PropertyFilterButton.scss'
import { Button } from 'antd'
import { AnyPropertyFilter } from '~/types'
import { CloseButton } from 'lib/components/CloseButton'
import { cohortsModel } from '~/models/cohortsModel'
import { useValues } from 'kea'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { midEllipsis } from 'lib/utils'
import { KEY_MAPPING } from 'lib/taxonomy'
import React from 'react'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
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
