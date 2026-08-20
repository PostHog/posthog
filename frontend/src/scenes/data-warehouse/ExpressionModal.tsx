import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { expressionModalLogic } from 'scenes/data-warehouse/expressionModalLogic'

export function ExpressionModal(): JSX.Element {
    const {
        isExpressionModalOpen,
        expressionToEdit,
        expressionSourceQuery,
        selectedTableName,
        error,
        isExpressionFormSubmitting,
        isPostHogTable,
    } = useValues(expressionModalLogic)
    const { closeExpressionModal } = useActions(expressionModalLogic)

    return (
        <LemonModal
            title={expressionToEdit ? 'Edit expression' : 'Add expression'}
            description={
                <span>
                    Add a SQL expression as a field on <code>{selectedTableName}</code>. It becomes available in every
                    query against this table.
                </span>
            }
            isOpen={isExpressionModalOpen}
            onClose={closeExpressionModal}
            width={600}
        >
            <Form
                logic={expressionModalLogic}
                formKey="expressionForm"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <Field name="field_name" label="Field name">
                    <LemonInput placeholder="for example browser_name" autoFocus={!expressionToEdit} />
                </Field>
                {isPostHogTable ? (
                    <LemonBanner type="info">
                        PostHog sometimes adds new fields to its built-in tables. If a new field takes this name, the
                        built-in field takes precedence and this expression stops applying. Use a unique prefix for your
                        field name, for example <code>acme_browser</code> instead of <code>browser</code>.
                    </LemonBanner>
                ) : null}
                <Field name="expression" label="Expression">
                    {({ value, onChange }) => (
                        <CodeEditorInline
                            data-attr="expression-modal-editor"
                            value={value ?? ''}
                            onChange={(newValue) => onChange(newValue ?? '')}
                            language="hogQLExpr"
                            minHeight="78px"
                            sourceQuery={expressionSourceQuery}
                        />
                    )}
                </Field>
                {error ? <LemonBanner type="error">{error}</LemonBanner> : null}
                <div className="flex flex-row justify-end gap-2">
                    <LemonButton type="secondary" onClick={closeExpressionModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" htmlType="submit" loading={isExpressionFormSubmitting}>
                        {expressionToEdit ? 'Update expression' : 'Add expression'}
                    </LemonButton>
                </div>
            </Form>
        </LemonModal>
    )
}
