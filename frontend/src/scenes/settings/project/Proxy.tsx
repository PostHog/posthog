import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { proxyLogic, ProxyRecord } from './proxyLogic'

export function Proxy(): JSX.Element {
    const { showingForm, proxyRecords } = useValues(proxyLogic)
    const { toggleShowingForm } = useActions(proxyLogic)

    const columns: LemonTableColumns<ProxyRecord> = [
        {
            title: 'Domain',
            dataIndex: 'domain',
        },
        {
            title: 'Status',
            dataIndex: 'status',
            render: function RenderStatus(status) {
                return <span className="capitalize">{status}</span>
            },
        },
    ]

    return (
        <div className="space-y-2">
            <LemonTable columns={columns} dataSource={proxyRecords} />
            {showingForm ? (
                <CreateRecordForm />
            ) : (
                <LemonButton onClick={toggleShowingForm} type="secondary" icon={<IconPlus />}>
                    Add domain
                </LemonButton>
            )}
        </div>
    )
}

function CreateRecordForm(): JSX.Element {
    const { proxyRecordsLoading } = useValues(proxyLogic)
    const { toggleShowingForm } = useActions(proxyLogic)

    return (
        <Form
            logic={proxyLogic}
            formKey="createRecord"
            enableFormOnSubmit
            className="w-full space-y-2 bg-bg-light rounded border p-2"
        >
            <LemonField name="domain">
                <LemonInput autoFocus placeholder="Enter a URL (e.g. https://posthog.com)" data-attr="domain-input" />
            </LemonField>
            <div className="flex justify-end gap-2">
                <LemonButton
                    type="secondary"
                    onClick={toggleShowingForm}
                    disabledReason={proxyRecordsLoading ? 'Saving' : undefined}
                >
                    Cancel
                </LemonButton>
                <LemonButton htmlType="submit" type="primary" data-attr="domain-save" loading={proxyRecordsLoading}>
                    Add
                </LemonButton>
            </div>
        </Form>
    )
}
