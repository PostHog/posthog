import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import { expressionModalLogic } from 'scenes/data-warehouse/expressionModalLogic'

import { NodeKind } from '~/queries/schema/schema-general'

export function ExpressionModal(): JSX.Element {
    const { isExpressionModalOpen, expressionToEdit, selectedTableName, error, isExpressionFormSubmitting } =
        useValues(expressionModalLogic)
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
                <Field name="expression" label="Expression">
                    {({ value, onChange }) => (
                        <CodeEditorInline
                            data-attr="expression-modal-editor"
                            value={value ?? ''}
                            onChange={(newValue) => onChange(newValue ?? '')}
                            language="hogQLExpr"
                            minHeight="78px"
                            sourceQuery={
                                selectedTableName
                                    ? { kind: NodeKind.HogQLQuery, query: `SELECT * FROM ${selectedTableName}` }
                                    : undefined
                            }
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
