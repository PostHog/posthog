import './PropertyFilterButton.scss'
import { Button } from 'antd'
import { AnyFilterLike, AnyPropertyFilter, CohortType, KeyMappingInterface, PropertyFilterValue } from '~/types'
import { CloseButton } from 'lib/components/CloseButton'
import { cohortsModel } from '~/models/cohortsModel'
import { useValues } from 'kea'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { allOperatorsMapping, isOperatorFlag, midEllipsis } from 'lib/utils'
import { KEY_MAPPING } from 'lib/taxonomy'
import React from 'react'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { isHogQLPropertyFilter } from '../utils'

export interface PropertyFilterButtonProps {
    onClick?: () => void
    onClose?: () => void
    children?: string
    item: AnyPropertyFilter
    style?: React.CSSProperties
}

export function formatPropertyLabel(
    item: Record<string, any>,
    cohortsById: Partial<Record<CohortType['id'], CohortType>>,
    keyMapping: KeyMappingInterface,
    valueFormatter: (value: PropertyFilterValue | undefined) => string | string[] | null = (s) => [String(s)]
): string {
    if (isHogQLPropertyFilter(item as AnyFilterLike)) {
        return extractExpressionComment(item.key)
    }
    const { value, key, operator, type } = item
    return type === 'cohort'
        ? cohortsById[value]?.name || `ID ${value}`
        : (keyMapping[type === 'element' ? 'element' : 'event'][key]?.label || key) +
              (isOperatorFlag(operator)
                  ? ` ${allOperatorsMapping[operator]}`
                  : ` ${(allOperatorsMapping[operator || 'exact'] || '?').split(' ')[0]} ${
                        value && value.length === 1 && value[0] === '' ? '(empty string)' : valueFormatter(value) || ''
                    } `)
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
