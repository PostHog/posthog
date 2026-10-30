import { useEffect, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSelect } from '@posthog/lemon-ui'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'

import { BIAggregation, BIDataSource } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier } from '~/queries/utils'

import { AGGREGATION_OPTIONS } from '../biEditorOptions'

export function BIExpressionPopover({
    visible,
    value,
    source,
    placeholder,
    aggregation,
    onChange,
    onClose,
    children,
}: {
    visible: boolean
    value: string
    source: BIDataSource
    placeholder?: string
    aggregation?: BIAggregation
    onChange: (value: string, aggregation?: BIAggregation) => void
    onClose: () => void
    children: React.ReactElement
}): JSX.Element {
    const [draftAggregation, setDraftAggregation] = useState(aggregation)
    useEffect(() => setDraftAggregation(aggregation), [aggregation, visible])

    return (
        <LemonDropdown
            visible={visible}
            closeOnClickInside={false}
            // The trigger opens a menu of its own, so only closing is handled here
            onVisibilityChange={(nextVisible) => !nextVisible && onClose()}
            placement="bottom-start"
            overlay={
                <div className="w-120 max-w-[max(60vw,20rem)]">
                    <div className="flex items-center justify-between border-b px-2 py-1">
                        <span className="font-semibold">
                            {aggregation ? 'Edit measure expression' : 'Edit expression'}
                        </span>
                        <LemonButton
                            icon={<IconX />}
                            size="xsmall"
                            type="tertiary"
                            aria-label="Close expression editor"
                            onClick={onClose}
                        />
                    </div>
                    {aggregation && (
                        <div className="flex flex-col gap-2 p-2">
                            <LemonSelect
                                aria-label="Expression aggregation"
                                value={draftAggregation}
                                onChange={setDraftAggregation}
                                options={AGGREGATION_OPTIONS.map((option) => ({
                                    ...option,
                                    label:
                                        option.value === 'custom' ? 'Custom SQL · no extra aggregation' : option.label,
                                }))}
                                data-attr="bi-expression-aggregation"
                            />
                            <p className="m-0 text-xs text-secondary">
                                {draftAggregation === 'custom'
                                    ? 'This expression calculates each group directly. No extra aggregation is added. Use aggregate functions such as sum, count, or avg.'
                                    : `${AGGREGATION_OPTIONS.find((option) => option.value === draftAggregation)?.label} is applied to this expression for each group. If your expression already includes aggregate functions, select Custom SQL.`}
                            </p>
                        </div>
                    )}
                    <HogQLEditor
                        value={value}
                        placeholder={
                            aggregation
                                ? draftAggregation === 'custom'
                                    ? 'For example: sum(amount) / nullIf(count(), 0)'
                                    : 'Enter a row expression using fields from the selected table.'
                                : placeholder
                        }
                        metadataSource={{
                            kind: NodeKind.HogQLQuery,
                            query: `SELECT * FROM ${escapeDottedHogQLIdentifier(source.table)}`,
                            connectionId: source.connectionId,
                        }}
                        onChange={(nextValue) => {
                            onChange(nextValue, draftAggregation)
                            onClose()
                        }}
                    />
                </div>
            }
        >
            <span className="inline-flex min-w-0 max-w-full">{children}</span>
        </LemonDropdown>
    )
}
