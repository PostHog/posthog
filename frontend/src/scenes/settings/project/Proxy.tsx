import { IconEllipsis, IconInfo, IconPlus } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonMenu,
    LemonTable,
    LemonTableColumns,
    LemonTabs,
    Spinner,
    Tooltip,
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
    const { formState, proxyRecords, proxyRecordsLoading } = useValues(proxyLogic)
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
                if (!status) {
                    return <span>Unknown</span>
                }

                return (
                    <div
                        className={clsx(
                            'space-x-1',
                            status === 'valid'
                                ? 'text-success'
                                : status == 'erroring'
                                ? 'text-danger'
                                : 'text-warning-dark'
                        )}
                    >
                        {status === 'issuing' && <Spinner />}
                        <span className="capitalize">{status === 'valid' ? 'live' : status}</span>
                        {status === 'waiting' && (
                            <Tooltip title="Waiting for DNS records to be created">
                                <IconInfo className="cursor-pointer" />
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
        {
            title: <span className="h-5" />,
            width: 20,
            className: 'flex justify-center',
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
                            <LemonButton size="small" icon={<IconEllipsis className="text-muted" />} />
                        </LemonMenu>
                    )
                )
            },
        },
    ]

    return (
        <div className="space-y-2">
            <LemonTable
                loading={proxyRecords.length === 0 && proxyRecordsLoading}
                columns={columns}
                dataSource={proxyRecords}
                expandable={{
                    expandedRowRender: (record) => <ExpandedRow record={record} />,
                }}
            />
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

const ExpandedRow = ({ record }: { record: ProxyRecord }): JSX.Element => {
    return (
        <div className="pb-4 pr-4">
            <LemonTabs
                size="small"
                activeKey="cname"
                tabs={[
                    {
                        label: 'CNAME',
                        key: 'cname',
                        content: (
                            <CodeSnippet key={record.id} language={Language.HTTP}>
                                {record.target_cname}
                            </CodeSnippet>
                        ),
                    },
                ]}
            />
        </div>
    )
}

function CreateRecordForm(): JSX.Element {
    const { formState, proxyRecordsLoading, proxyRecords } = useValues(proxyLogic)
    const { collapseForm } = useActions(proxyLogic)

    const waitingRecords = proxyRecords.filter((r) => r.status === 'waiting')

    return (
        <div className="bg-bg-light rounded border px-5 py-4 space-y-2">
            {formState == 'active' ? (
                <Form logic={proxyLogic} formKey="createRecord" enableFormOnSubmit className="w-full space-y-2">
                    <LemonField name="domain">
                        <LemonInput
                            autoFocus
                            placeholder="Enter a domain (e.g. ph.mydomain.com)"
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
                        You need to set the following <b>CNAME</b> records in your DNS provider:
                    </div>
                    {waitingRecords.map((r) => (
                        <div key={r.id} className="space-y-1">
                            <span className="font-semibold">{r.domain}</span>
                            <CodeSnippet key={r.id} language={Language.HTTP}>
                                {r.target_cname}
                            </CodeSnippet>
                        </div>
                    ))}
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
