import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'
import {
    AGGREGATION_OPTIONS,
    DATE_BUCKET_OPTIONS,
    NUMERIC_AGGREGATIONS,
} from 'products/business_intelligence/frontend/biEditorOptions'
import {
    BIShelf,
    getBIFieldPillLabel,
    getBIShelfEditorKey,
    getBIValuePillLabel,
    getBIValueSortKey,
    isNumericBIField,
} from 'products/business_intelligence/frontend/biEditorTypes'
import { BIExpressionPopover } from 'products/business_intelligence/frontend/components/BIExpressionPopover'
import { BIPill } from 'products/business_intelligence/frontend/components/BIPill'

import { BIFieldNameModal } from './BIFieldNameModal'
import { BIShelfDropTarget } from './BIShelfDropTarget'

type ExpressionTarget = 'field' | 'aggregation'

/** A dimension on rows or columns, or a measure from the values shelf. */
export function BIFieldPill({
    shelf,
    index,
}: {
    shelf: Exclude<BIShelf, 'filters'>
    index: number
}): JSX.Element | null {
    const [nameDraft, setNameDraft] = useState<string | null>(null)
    const { config, activeExpressionEditorId, activeExpressionEditorTarget, sortOptions } = useValues(biEditorLogic)
    const {
        addFieldToShelf,
        convertMeasureToDimension,
        duplicateField,
        editCalculatedField,
        editCalculatedMeasure,
        moveFieldToShelf,
        removeFieldFromShelf,
        setActiveExpressionEditorId,
        setFieldDateBucket,
        setFieldDatePart,
        setFieldExpression,
        setMeasureExpression,
        setSort,
        setValueAggregation,
        renameField,
    } = useActions(biEditorLogic)

    const value = shelf === 'values' ? config.values[index] : null
    const field = value ? value.field : shelf === 'values' ? null : config[shelf][index]
    if (!field) {
        return null
    }

    const isMeasure = shelf === 'values'
    const isCalculatedMeasure = value?.aggregation === 'custom' && !!value.label
    const occurrence = isMeasure
        ? config.values.slice(0, index).filter((previous) => previous.field.id === field.id).length
        : 0
    const editorKey = `${getBIShelfEditorKey(shelf, field.id)}${occurrence ? `:${occurrence + 1}` : ''}`
    const expressionTarget = activeExpressionEditorId === editorKey ? activeExpressionEditorTarget : null
    const setEditing = (target: ExpressionTarget): void => setActiveExpressionEditorId(editorKey, target)
    const candidateSortKey = isMeasure ? getBIValueSortKey(config, index) : `${shelf}:${field.id}`
    const sortKey = sortOptions.some((option) => option.key === candidateSortKey) ? candidateSortKey : null
    const otherDimensionShelf = shelf === 'rows' ? 'columns' : 'rows'
    const label = value ? getBIValuePillLabel(value) : getBIFieldPillLabel(field)
    const incomplete = value?.aggregation === 'custom' ? !value.customExpression?.trim() : !field.expression.trim()

    const items: LemonMenuItems = [
        isMeasure && value && !isCalculatedMeasure
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
                          if (option.value === 'custom') {
                              setEditing('aggregation')
                          } else {
                              setValueAggregation(index, option.value)
                          }
                      },
                  })),
              }
            : null,
        ['date', 'datetime'].includes(field.type)
            ? {
                  title: 'Timeline (keeps the year)',
                  items: DATE_BUCKET_OPTIONS.map((option) => ({
                      label: option.label,
                      active: !field.datePart && (field.dateBucket ?? null) === option.value,
                      onClick: () => setFieldDateBucket(shelf, index, option.value),
                  })),
              }
            : null,
        ['date', 'datetime'].includes(field.type)
            ? {
                  title: 'Date part (combines years)',
                  items: (
                      [
                          ['month', 'Month of year'],
                          ['quarter', 'Quarter of year'],
                          ['day_of_week', 'Day of week'],
                      ] as const
                  ).map(([part, label]) => ({
                      label,
                      active: field.datePart === part,
                      onClick: () => setFieldDatePart(shelf, index, part),
                  })),
              }
            : null,
        {
            items: [
                { label: 'Rename', onClick: () => setNameDraft(label) },
                { label: 'Duplicate', onClick: () => duplicateField(shelf, index) },
                isMeasure
                    ? {
                          label: value?.shelf === 'columns' ? 'Move to rows' : 'Move to columns',
                          onClick: () =>
                              moveFieldToShelf('values', index, value?.shelf === 'columns' ? 'rows' : 'columns'),
                      }
                    : null,
                field.localDefinition?.kind === 'expression'
                    ? {
                          label: 'Edit calculated field',
                          onClick: () => editCalculatedField({ ...field, id: field.localFieldId ?? field.id }),
                      }
                    : !isCalculatedMeasure
                      ? {
                            label: isMeasure ? 'Edit measure expression' : 'Edit field expression',
                            onClick: () => setEditing('field'),
                        }
                      : null,
                value?.aggregation === 'custom' && field.localDefinition?.kind !== 'expression'
                    ? { label: 'Edit calculated measure', onClick: () => editCalculatedMeasure(index) }
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
                    ? {
                          label: 'Convert to dimension',
                          disabledReason: isCalculatedMeasure ? 'Calculated measures aggregate each group' : undefined,
                          onClick: () => convertMeasureToDimension(index),
                      }
                    : { label: 'Convert to measure', onClick: () => moveFieldToShelf(shelf, index, 'values') },
                !isMeasure
                    ? {
                          label: `Move to ${otherDimensionShelf}`,
                          onClick: () => moveFieldToShelf(shelf, index, otherDimensionShelf),
                      }
                    : null,
                {
                    label: 'Add to filters',
                    disabledReason: isCalculatedMeasure ? 'Filters apply before calculated measures' : undefined,
                    onClick: () => addFieldToShelf(field, 'filters'),
                },
            ],
        },
        {
            items: [{ label: 'Remove', status: 'danger', onClick: () => removeFieldFromShelf(shelf, index) }],
        },
    ]

    return (
        <>
            {nameDraft !== null && (
                <BIFieldNameModal
                    name={nameDraft}
                    onSave={(name) => renameField(shelf, index, name)}
                    onClose={() => setNameDraft(null)}
                />
            )}
            <BIExpressionPopover
                visible={expressionTarget !== null}
                value={
                    expressionTarget === 'aggregation' || value?.aggregation === 'custom'
                        ? (value?.customExpression ?? field.expression)
                        : field.expression
                }
                source={field.source}
                aggregation={expressionTarget === 'aggregation' ? 'custom' : value?.aggregation}
                placeholder={expressionTarget === 'aggregation' ? 'For example: sum(amount) / count()' : undefined}
                onChange={(nextExpression, aggregation) =>
                    aggregation
                        ? setMeasureExpression(index, nextExpression, aggregation)
                        : setFieldExpression(shelf, index, nextExpression)
                }
                onClose={() => {
                    if (activeExpressionEditorId === editorKey) {
                        setActiveExpressionEditorId(null)
                    }
                }}
            >
                <BIShelfDropTarget shelf={shelf} index={index} className="inline-flex min-w-0 max-w-[min(18rem,100%)]">
                    <LemonMenu items={items} placement="bottom-start">
                        <BIPill
                            kind={isMeasure ? 'measure' : 'dimension'}
                            label={label}
                            shelf={shelf}
                            index={index}
                            incomplete={incomplete}
                            aria-label={`${label} options`}
                            data-attr={`bi-editor-${shelf}-pill`}
                        />
                    </LemonMenu>
                </BIShelfDropTarget>
            </BIExpressionPopover>
        </>
    )
}
