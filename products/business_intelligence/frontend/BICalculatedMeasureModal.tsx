import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'

import { NodeKind } from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier } from '~/queries/utils'

import { biEditorLogic } from 'products/business_intelligence/frontend/biEditorLogic'

export function BICalculatedMeasureModal(): JSX.Element | null {
    const {
        calculatedMeasureDraft: draft,
        calculatedFieldError,
        calculatedFieldValidation,
        calculatedFieldMetadata,
        config,
    } = useValues(biEditorLogic)
    const { setCalculatedMeasureDraft, saveCalculatedMeasure } = useActions(biEditorLogic)

    if (!draft || !config.source) {
        return null
    }

    return (
        <LemonModal
            isOpen
            title={draft.index === null && !draft.fieldId ? 'Add calculated field' : 'Edit calculated field'}
            onClose={() => setCalculatedMeasureDraft(null)}
            width="36rem"
            data-attr="bi-calculated-measure-modal"
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => setCalculatedMeasureDraft(null)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveCalculatedMeasure}
                        loading={calculatedFieldValidation === 'checking'}
                        disabledReason={
                            calculatedFieldError ??
                            (calculatedFieldValidation !== 'valid' ? 'Enter a valid SQL expression' : undefined)
                        }
                        data-attr="bi-calculated-measure-save"
                    >
                        {draft.index === null && !draft.fieldId ? 'Add field' : 'Save field'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <p className="m-0 text-secondary">
                    This field stays in this worksheet. Editing it updates every use here. It does not add a field to
                    the source table.
                </p>
                <div className="flex flex-wrap gap-3">
                    <LemonSelect
                        aria-label="Calculated field role"
                        value={draft.kind ?? 'measure'}
                        options={[
                            { value: 'dimension', label: 'Dimension · one value per row' },
                            { value: 'measure', label: 'Measure · aggregate each group' },
                        ]}
                        onChange={(kind) => setCalculatedMeasureDraft({ ...draft, kind })}
                        disabledReason={
                            draft.fieldId || draft.index !== null ? 'Create a new field to change its role' : undefined
                        }
                    />
                    {draft.kind === 'dimension' && (
                        <LemonSelect
                            aria-label="Calculated field type"
                            value={draft.type ?? 'string'}
                            options={[
                                { value: 'string', label: 'Text' },
                                { value: 'integer', label: 'Integer' },
                                { value: 'float', label: 'Number' },
                                { value: 'boolean', label: 'Boolean' },
                                { value: 'date', label: 'Date' },
                                { value: 'datetime', label: 'Date and time' },
                                { value: 'boolean', label: 'Boolean' },
                            ]}
                            onChange={(type) => setCalculatedMeasureDraft({ ...draft, type, typeOverride: true })}
                        />
                    )}
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="bi-calculated-measure-name">Name</LemonLabel>
                    <LemonInput
                        id="bi-calculated-measure-name"
                        value={draft.name}
                        onChange={(name) => setCalculatedMeasureDraft({ ...draft, name })}
                        placeholder={draft.kind === 'dimension' ? 'For example, Plan' : 'For example, ARPU'}
                        autoFocus
                        data-attr="bi-calculated-measure-name"
                    />
                </div>
                <div className="flex flex-col gap-2">
                    <LemonLabel>HogQL expression</LemonLabel>
                    <CodeEditorInline
                        value={draft.expression}
                        onChange={(expression) =>
                            setCalculatedMeasureDraft({ ...draft, expression: expression ?? '', typeOverride: false })
                        }
                        language="hogQLExpr"
                        minHeight="100px"
                        options={{ ariaLabel: 'Calculated field expression' }}
                        sourceQuery={{
                            kind: NodeKind.HogQLQuery,
                            query: `SELECT * FROM ${escapeDottedHogQLIdentifier(config.source.table)}`,
                            connectionId: config.source.connectionId,
                        }}
                        onPressCmdEnter={saveCalculatedMeasure}
                        data-attr="bi-calculated-measure-formula"
                    />
                    <p className="m-0 text-xs text-secondary">Press Ctrl+Space to autocomplete fields.</p>
                    <p className="m-0 text-xs" role="status">
                        {calculatedFieldValidation === 'checking'
                            ? 'Checking SQL…'
                            : calculatedFieldValidation === 'valid'
                              ? 'Valid SQL'
                              : calculatedFieldValidation === 'invalid'
                                ? (calculatedFieldMetadata?.metadata.errors[0]?.message ?? 'Invalid SQL expression')
                                : ''}
                    </p>
                    <p className="m-0 text-xs text-secondary">
                        {draft.kind === 'dimension'
                            ? "Use a row expression, such as coalesce(properties.plan, 'Unknown'). Refer to fields from the selected table using HogQL."
                            : 'Use aggregate functions such as sum, count, and avg. The expression runs for each group after row filters.'}
                    </p>
                    {draft.kind !== 'dimension' && (
                        <div className="rounded border bg-surface-primary p-2 text-xs">
                            <div className="mb-1 font-semibold">Average revenue per user</div>
                            <code className="break-words">sum(revenue) / nullIf(count(DISTINCT user_id), 0)</code>
                            <p className="mb-0 mt-1 text-secondary">
                                Replace revenue and user_id with your fields. nullIf avoids division by zero.
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
