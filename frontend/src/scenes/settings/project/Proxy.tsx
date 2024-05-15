import { IconEllipsis, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonMenu,
    LemonTable,
    LemonTableColumns,
    Spinner,
} from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { proxyLogic, ProxyRecord } from './proxyLogic'

export function Proxy(): JSX.Element {
    const { isCloudOrDev } = useValues(preflightLogic)
    const { formState, proxyRecords } = useValues(proxyLogic)
    const { showForm, deleteRecord } = useActions(proxyLogic)

    if (!isCloudOrDev) {
        return <LemonBanner type="warning">Using a reverse proxy only works in PostHog Cloud</LemonBanner>
    }

    const columns: LemonTableColumns<ProxyRecord> = [
        {
            title: 'Domain',
            dataIndex: 'domain',
        },
        {
            title: 'Status',
            dataIndex: 'status',
            render: function RenderStatus(status) {
                return (
                    <div>
                        <span
                            className={clsx(
                                'capitalize',
                                status === 'valid'
                                    ? 'text-success'
                                    : status == 'erroring'
                                    ? 'text-danger'
                                    : 'text-warning'
                            )}
                        >
                            {status}
                        </span>
                        {status === 'issuing' && <Spinner />}
                    </div>
                )
            },
        },
        {
            title: 'Actions',
            render: function Render(_, { id, status }) {
                return (
                    status != 'deleting' && (
                        <LemonMenu
                            items={[
                                {
                                    label: 'Delete',
                                    status: 'danger',
                                    onClick: () => deleteRecord(id),
                                },
                            ]}
                        >
                            <LemonButton size="xsmall" icon={<IconEllipsis />} />
                        </LemonMenu>
                    )
                )
            },
        },
    ]

    return (
        <div className="space-y-2">
            <LemonTable columns={columns} dataSource={proxyRecords} />
            {formState === 'collapsed' ? (
                <LemonButton onClick={showForm} type="secondary" icon={<IconPlus />}>
                    Add domain
                </LemonButton>
            ) : (
                <CreateRecordForm />
            )}
        </div>
    )
}

function CreateRecordForm(): JSX.Element {
    const { formState, proxyRecordsLoading } = useValues(proxyLogic)
    const { collapseForm } = useActions(proxyLogic)

    return (
        <div className="bg-bg-light rounded border p-2 space-y-2">
            {formState == 'active' ? (
                <Form logic={proxyLogic} formKey="createRecord" enableFormOnSubmit className="w-full space-y-2">
                    <LemonField name="domain">
                        <LemonInput
                            autoFocus
                            placeholder="Enter a URL (e.g. https://posthog.com)"
                            data-attr="domain-input"
                        />
                    </LemonField>
                    <div className="flex justify-end gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={collapseForm}
                            disabledReason={proxyRecordsLoading ? 'Saving' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            htmlType="submit"
                            type="primary"
                            data-attr="domain-save"
                            loading={proxyRecordsLoading}
                        >
                            Add
                        </LemonButton>
                    </div>
                </Form>
            ) : (
                <>
                    <div className="text-xl font-semibold leading-tight">Almost there</div>
                    <div>
                        You need to set the <b>CNAME</b> record on your DNS provider:
                    </div>
                    <CodeSnippet language={Language.HTTP}>sdfghgfdsdfghgfdsw.com</CodeSnippet>
                    <div className="flex justify-end">
                        <LemonButton onClick={collapseForm} type="primary">
                            Done
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
