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
                                    router.actions.push(urls.dataWarehouse())
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
                        placeholder="Examples: stripe_invoice, hubspot_contacts, users"
                        autoComplete="off"
                        autoCapitalize="off"
                        autoCorrect="off"
                        spellCheck={false}
                    />
                </Field>
                <div className="text-muted text-xs mb-4">This will be the table name used when writing queries</div>
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
                <div className="text-muted text-xs mb-4">
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
            </div>
        </Form>
    )
}
