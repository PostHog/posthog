import { SceneExport } from 'scenes/sceneTypes'
import { dataWarehouseTableLogic } from './dataWarehouseTableLogic'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, Link } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { Field } from 'lib/forms/Field'

export const scene: SceneExport = {
    component: DataWarehousetTable,
    logic: dataWarehouseTableLogic,
    paramsToProps: ({ params: { id } }): (typeof dataWarehouseTableLogic)['props'] => ({
        id: id,
    }),
}

export function DataWarehousetTable({ id }: { id?: string } = {}): JSX.Element {
    const { isEditingTable } = useValues(dataWarehouseTableLogic)
    const showTableForm = id === 'new' || isEditingTable
    return <div>{!id ? <LemonSkeleton /> : <>{showTableForm ? <TableForm id={id} /> : <></>}</>}</div>
}

export function TableForm({ id }: { id: string }): JSX.Element {
    const { table, tableLoading, isEditingTable } = useValues(dataWarehouseTableLogic)
    const { loadTable, editingTable } = useActions(dataWarehouseTableLogic)

    return (
        <Form formKey="table" logic={dataWarehouseTableLogic} className="space-y-4" enableFormOnSubmit>
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
                caption={
                    <div>
                        External tables are supported through object storage systems like S3.{' '}
                        <Link
                            to="https://posthog.com/docs/data/data-warehouse#step-1-creating-a-bucket-in-s3"
                            target="_blank"
                        >
                            Learn how to set up your data
                        </Link>
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
                            { label: 'JSON', value: 'JSONEachRow' },
                        ]}
                    />
                </Field>
                <Field name={['credential', 'access_key']} label="Access Key">
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
                <Field name={['credential', 'access_secret']} label="Access Secret">
                    <LemonInput
                        data-attr="access-secret"
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
        </Form>
    )
}
