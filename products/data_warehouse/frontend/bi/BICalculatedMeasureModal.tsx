import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { biEditorLogic } from 'scenes/data-warehouse/editor/bi/biEditorLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier } from '~/queries/utils'

export function BICalculatedMeasureModal(): JSX.Element | null {
    const { calculatedMeasureDraft: draft, config } = useValues(biEditorLogic)
    const { setCalculatedMeasureDraft, saveCalculatedMeasure } = useActions(biEditorLogic)

    if (!draft || !config.source) {
        return null
    }

    return (
        <LemonModal
            isOpen
            title={draft.index === null ? 'Add calculated measure' : 'Edit calculated measure'}
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
                        disabledReason={
                            !draft.name.trim()
                                ? 'Enter a name for this measure'
                                : !draft.expression.trim()
                                  ? 'Enter a formula for this measure'
                                  : undefined
                        }
                        data-attr="bi-calculated-measure-save"
                    >
                        {draft.index === null ? 'Add measure' : 'Save measure'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                    <LemonLabel htmlFor="bi-calculated-measure-name">Name</LemonLabel>
                    <LemonInput
                        id="bi-calculated-measure-name"
                        value={draft.name}
                        onChange={(name) => setCalculatedMeasureDraft({ ...draft, name })}
                        placeholder="For example, ARPU"
                        autoFocus
                        data-attr="bi-calculated-measure-name"
                    />
                </div>
                <div className="flex flex-col gap-2">
                    <LemonLabel>Formula</LemonLabel>
                    <CodeEditorInline
                        value={draft.expression}
                        onChange={(expression) => setCalculatedMeasureDraft({ ...draft, expression: expression ?? '' })}
                        language="hogQLExpr"
                        minHeight="100px"
                        options={{ ariaLabel: 'Calculated measure formula' }}
                        sourceQuery={{
                            kind: NodeKind.HogQLQuery,
                            query: `SELECT * FROM ${escapeDottedHogQLIdentifier(config.source.table)}`,
                            connectionId: config.source.connectionId,
                        }}
                        onPressCmdEnter={saveCalculatedMeasure}
                        data-attr="bi-calculated-measure-formula"
                    />
                    <p className="m-0 text-xs text-secondary">
                        Use SQL aggregate functions such as sum, count, and avg. The formula is calculated for each
                        group on your worksheet, after filters are applied.
                    </p>
                    <div className="rounded border bg-surface-primary p-2 text-xs">
                        <div className="mb-1 font-semibold">Average revenue per user</div>
                        <code className="break-words">sum(revenue) / nullIf(count(DISTINCT user_id), 0)</code>
                        <p className="mb-0 mt-1 text-secondary">
                            Replace revenue and user_id with your fields. nullIf avoids division by zero.
                        </p>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
