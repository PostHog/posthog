import { useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { dataDeletionLogic } from './dataDeletionLogic'

export function DataDeletionPreviewPanel(): JSX.Element | null {
    const { preview, previewLoading, previewIsFresh } = useValues(dataDeletionLogic)

    if (previewLoading && !preview) {
        return <LemonSkeleton className="h-24" />
    }

    if (!preview) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            {!previewIsFresh && (
                <LemonBanner type="info">
                    Form has changed since this preview ran. Re-run the preview to refresh the result.
                </LemonBanner>
            )}
            <LemonBanner type={preview.count === 0 ? 'info' : 'warning'}>
                <b>{preview.count.toLocaleString()}</b>{' '}
                {preview.count === 0 ? 'events match — nothing to delete.' : 'events would be affected'}
                {preview.count > 0 && preview.min_timestamp && preview.max_timestamp && (
                    <>
                        {' '}
                        between <TZLabel time={preview.min_timestamp} timestampStyle="absolute" /> and{' '}
                        <TZLabel time={preview.max_timestamp} timestampStyle="absolute" />.
                    </>
                )}
                {preview.truncated && (
                    <>
                        {' '}
                        The preview below is limited to {preview.limit.toLocaleString()} rows, but deletion will cover
                        every matching event.
                    </>
                )}
            </LemonBanner>
            {preview.count > 0 && (
                <LemonTable
                    dataSource={preview.rows}
                    rowKey="uuid"
                    columns={[
                        { title: 'Event', dataIndex: 'event', width: 180 },
                        {
                            title: 'Timestamp',
                            dataIndex: 'timestamp',
                            render: (value) =>
                                value ? <TZLabel time={value as string} timestampStyle="absolute" /> : '—',
                        },
                        { title: 'Distinct ID', dataIndex: 'distinct_id', width: 200 },
                        {
                            title: 'Properties',
                            dataIndex: 'properties',
                            render: (value) => (
                                <code className="text-xs">{(value as string)?.slice(0, 200) ?? ''}</code>
                            ),
                        },
                    ]}
                    pagination={{ pageSize: 20 }}
                />
            )}
        </div>
    )
}
