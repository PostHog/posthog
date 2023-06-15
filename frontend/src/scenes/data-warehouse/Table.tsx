import { SceneExport } from 'scenes/sceneTypes'
import { tableLogic } from './tableLogic'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonButton, LemonDivider, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Field } from 'lib/forms/Field'

export const scene: SceneExport = {
    component: Table,
    logic: tableLogic,
    paramsToProps: ({ params: { id } }): (typeof tableLogic)['props'] => ({
        id: id,
    }),
}

export function Table({ id }: { id?: string } = {}): JSX.Element {
    const { isEditingTable } = useValues(tableLogic)
    const showTableForm = id === 'new' || isEditingTable
    return <div>{!id ? <LemonSkeleton /> : <>{showTableForm ? <TableForm id={id} /> : <></>}</>}</div>
}

export function TableForm({ id }: { id: string }): JSX.Element {
    const { table, tableLoading, isEditingTable } = useValues(tableLogic)
    const { loadTable, editingTable } = useActions(tableLogic)

    return (
        <Form formKey="table" logic={tableLogic} className="space-y-4" enableFormOnSubmit>
            <PageHeader
                title={id === 'new' ? 'New table' : table.name}
                buttons={
                    <div className="flex items-center gap-2">
                        <LemonButton
                            data-attr="cancel-table"
                            type="secondary"
                            loading={tableLoading}
                            onClick={() => {
                                if (isEditingTable) {
                                    editingTable(false)
                                    loadTable()
                                } else {
                                    router.actions.push(urls.tables())
                                }
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="save-feature-flag"
                            htmlType="submit"
                            loading={tableLoading}
                        >
                            Save
                        </LemonButton>
                    </div>
                }
            />
            <LemonDivider />
            <div className="flex flex-col gap-2 max-w-160">
                <Field name="name" label="Table Name">
                    <LemonInput
                        data-attr="table-name"
                        className="ph-ignore-input"
                        autoFocus
                        placeholder="examples: stripe_invoice, hubspot_contacts, users"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </Field>
                <Field name="url_pattern" label="Files URL pattern">
                    <LemonInput
                        data-attr="table-name"
                        className="ph-ignore-input"
                        autoFocus
                        placeholder="eg: https://your-org.s3.amazonaws.com/airbyte/stripe/invoices/*.pqt"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </Field>
                <div className="text-muted mb-4">
                    You can use <strong>*</strong> to select multiple files.
                </div>
                <Field name="format" label="File format" className="w-max">
                    <LemonSelect
                        data-attr="table-format"
                        options={[
                            { label: 'Parquet (recommended)', value: 'Parquet' },
                            { label: 'CSV', value: 'CSV' },
                        ]}
                    />
                </Field>
                <Field name="access_key" label="Access Key">
                    <LemonInput
                        data-attr="access-key"
                        className="ph-ignore-input"
                        autoFocus
                        placeholder="eg: AKIAIOSFODNN7EXAMPLE"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </Field>
                <Field name="access_secret" label="Access Secret">
                    <LemonInput
                        data-attr="access-key"
                        className="ph-ignore-input"
                        autoFocus
                        type="password"
                        placeholder="eg: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </Field>
            </div>
            <LemonDivider />
            <div className="flex items-center gap-2 justify-end">
                <LemonButton
                    data-attr="cancel-table"
                    type="secondary"
                    loading={tableLoading}
                    onClick={() => {
                        if (isEditingTable) {
                            editingTable(false)
                            loadTable()
                        } else {
                            router.actions.push(urls.tables())
                        }
                    }}
                >
                    Cancel
                </LemonButton>
                <LemonButton type="primary" data-attr="save-feature-flag" htmlType="submit" loading={tableLoading}>
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
