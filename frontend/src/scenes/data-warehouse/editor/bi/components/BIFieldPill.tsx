import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { biEditorLogic } from '../biEditorLogic'
import { AGGREGATION_OPTIONS, DATE_BUCKET_OPTIONS, NUMERIC_AGGREGATIONS } from '../biEditorOptions'
import {
    BIShelf,
    getBIFieldPillLabel,
    getBIValuePillLabel,
    getBIValueSortKey,
    isDateTimeBIField,
    isNumericBIField,
} from '../biEditorTypes'
import { BIExpressionPopover } from './BIExpressionPopover'
import { BIPill } from './BIPill'

type ExpressionTarget = 'field' | 'aggregation'

/** A dimension on rows or columns, or a measure from the values shelf. */
export function BIFieldPill({
    shelf,
    index,
}: {
    shelf: Exclude<BIShelf, 'filters'>
    index: number
}): JSX.Element | null {
    const { config, activeExpressionEditorId } = useValues(biEditorLogic)
    const {
        addFieldToShelf,
        moveFieldToShelf,
        removeFieldFromShelf,
        setActiveExpressionEditorId,
        setFieldDateBucket,
        setFieldExpression,
        setSort,
        setValueAggregation,
        setValueCustomExpression,
    } = useActions(biEditorLogic)
    const [editing, setEditing] = useState<ExpressionTarget | null>(null)

    const value = shelf === 'values' ? config.values[index] : null
    const field = value ? value.field : shelf === 'values' ? null : config[shelf][index]
    if (!field) {
        return null
    }

    const isMeasure = shelf === 'values'
    const autoOpen = activeExpressionEditorId === field.id
    const expressionTarget: ExpressionTarget | null = editing ?? (autoOpen ? 'field' : null)
    const sortKey = isMeasure ? getBIValueSortKey(config, index) : `${shelf}:${field.id}`
    const otherDimensionShelf = shelf === 'rows' ? 'columns' : 'rows'
    const label = value ? getBIValuePillLabel(value) : getBIFieldPillLabel(field)
    const incomplete = value?.aggregation === 'custom' ? !value.customExpression?.trim() : !field.expression.trim()

    const items: LemonMenuItems = [
        isMeasure && value
            ? {
                  title: 'Measure',
                  items: AGGREGATION_OPTIONS.map((option) => ({
                      label: option.label,
                      active: value.aggregation === option.value,
                      disabledReason:
                          !isNumericBIField(field) && NUMERIC_AGGREGATIONS.includes(option.value)
                              ? 'This calculation needs a numeric field'
                              : undefined,
                      onClick: () => {
                          setValueAggregation(index, option.value)
                          if (option.value === 'custom' && !value.customExpression) {
                              setEditing('aggregation')
                          }
                      },
                  })),
              }
            : null,
        isDateTimeBIField(field)
            ? {
                  title: 'Date',
                  items: DATE_BUCKET_OPTIONS.map((option) => ({
                      label: option.label,
                      active: (field.dateBucket ?? null) === option.value,
                      onClick: () => setFieldDateBucket(shelf, index, option.value),
                  })),
              }
            : null,
        {
            items: [
                { label: 'Edit field expression', onClick: () => setEditing('field') },
                value?.aggregation === 'custom'
                    ? { label: 'Edit SQL aggregation', onClick: () => setEditing('aggregation') }
                    : null,
                sortKey
                    ? {
                          label: 'Sort ascending',
                          icon: <IconArrowUp />,
                          onClick: () => setSort({ key: sortKey, direction: 'asc' }),
                      }
                    : null,
                sortKey
                    ? {
                          label: 'Sort descending',
                          icon: <IconArrowDown />,
                          onClick: () => setSort({ key: sortKey, direction: 'desc' }),
                      }
                    : null,
            ],
        },
        {
            items: [
                isMeasure
                    ? { label: 'Convert to dimension', onClick: () => moveFieldToShelf('values', index, 'rows') }
                    : { label: 'Convert to measure', onClick: () => moveFieldToShelf(shelf, index, 'values') },
                !isMeasure
                    ? {
                          label: `Move to ${otherDimensionShelf}`,
                          onClick: () => moveFieldToShelf(shelf, index, otherDimensionShelf),
                      }
                    : null,
                { label: 'Add to filters', onClick: () => addFieldToShelf(field, 'filters') },
            ],
        },
        {
            items: [{ label: 'Remove', status: 'danger', onClick: () => removeFieldFromShelf(shelf, index) }],
        },
    ]

    return (
        <BIExpressionPopover
            visible={expressionTarget !== null}
            value={expressionTarget === 'aggregation' ? (value?.customExpression ?? '') : field.expression}
            source={field.source}
            placeholder={expressionTarget === 'aggregation' ? 'For example: sum(amount) / count()' : undefined}
            onChange={(nextExpression) =>
                expressionTarget === 'aggregation'
                    ? setValueCustomExpression(index, nextExpression)
                    : setFieldExpression(shelf, index, nextExpression)
            }
            onClose={() => {
                setEditing(null)
                if (autoOpen) {
                    setActiveExpressionEditorId(null)
                }
            }}
        >
            <span className="inline-flex min-w-0">
                <LemonMenu items={items} placement="bottom-start">
                    <BIPill
                        kind={isMeasure ? 'measure' : 'dimension'}
                        label={label}
                        shelf={shelf}
                        index={index}
                        incomplete={incomplete}
                        onDropOutside={() => removeFieldFromShelf(shelf, index)}
                        aria-label={`${label} options`}
                        data-attr={`bi-editor-${shelf}-pill`}
                    />
                </LemonMenu>
            </span>
        </BIExpressionPopover>
    )
}
