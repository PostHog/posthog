import { useActions, useValues } from 'kea'

import {
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Item,
    ItemContent,
    ItemDescription,
    Skeleton,
} from '@posthog/quill'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { ProxyRecord, proxyLogic } from './proxyLogic'
import { ProxySDKSetup } from './ProxySDKSetup'
import { QuillCloudflareOptIn } from './QuillCloudflareOptIn'
import { QuillProxyCreateRecordForm } from './QuillProxyCreateRecordForm'
import { QuillProxyRecordRow } from './QuillProxyRecordRow'
import { QuillProxyWaitingRecords } from './QuillProxyWaitingRecords'

export function QuillManagedReverseProxy({
    restrictionReason,
    showCloudflareOptIn,
    onDelete,
}: {
    restrictionReason: string | null
    showCloudflareOptIn: boolean
    onDelete: (id: ProxyRecord['id']) => void
}): JSX.Element {
    const { formState, proxyRecords, proxyRecordsLoading, maxProxyRecords } = useValues(proxyLogic)
    const { acknowledgeCloudflareOptIn, showForm } = useActions(proxyLogic)

    if (showCloudflareOptIn) {
        return <QuillCloudflareOptIn onAcknowledge={acknowledgeCloudflareOptIn} restrictionReason={restrictionReason} />
    }

    const maxRecordsReached = proxyRecords.length >= maxProxyRecords
    const recordsWithMessages = proxyRecords.filter((record) => !!record.message)
    const validProxyRecords = proxyRecords.filter((record) => record.status === 'valid')

    return (
        <div className="flex flex-col gap-2">
            {recordsWithMessages.map((r) => (
                <Item tone="warning" size="sm" key={r.id}>
                    <ItemContent className="text-xs">
                        <LemonMarkdown>{`**${r.domain}**\n ${r.message}`}</LemonMarkdown>
                    </ItemContent>
                </Item>
            ))}

            {proxyRecords.length === 0 && proxyRecordsLoading ? (
                <Skeleton className="h-12 w-full" />
            ) : (
                proxyRecords.map((record) => (
                    <QuillProxyRecordRow
                        key={record.id}
                        record={record}
                        restrictionReason={restrictionReason}
                        onDelete={onDelete}
                    />
                ))
            )}

            <QuillProxyWaitingRecords />

            {validProxyRecords.length > 0 && (
                <Card size="sm">
                    <CardHeader>
                        <CardTitle>Update your SDK configuration</CardTitle>
                        <CardDescription>
                            Now that your proxy is live, update your SDK initialization to send data through your custom
                            domain.
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        <ProxySDKSetup />
                    </CardContent>
                </Card>
            )}

            {formState === 'collapsed' ? (
                maxRecordsReached ? (
                    <Item tone="info" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                {`There is a maximum of ${maxProxyRecords} proxy records allowed per organization.`}
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                ) : (
                    <div className="flex">
                        <Button variant="primary" onClick={showForm} disabledReason={restrictionReason}>
                            Add managed proxy
                        </Button>
                    </div>
                )
            ) : (
                <QuillProxyCreateRecordForm />
            )}
        </div>
    )
}
