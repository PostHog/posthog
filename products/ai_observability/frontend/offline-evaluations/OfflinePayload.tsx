import { LemonCollapse } from '@posthog/lemon-ui'

import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { cn } from 'lib/utils/css-classes'

import type { OfflineItemPayloadReadApi, OfflineResultPayloadReadApi } from '../generated/api.schemas'

export function OfflinePayload({
    payload,
    fields,
}: {
    payload: OfflineItemPayloadReadApi | OfflineResultPayloadReadApi
    fields: Array<
        keyof NonNullable<OfflineItemPayloadReadApi['data']> | keyof NonNullable<OfflineResultPayloadReadApi['data']>
    >
}): JSX.Element {
    if (!payload.available || payload.data === null) {
        return (
            <p className="text-muted">
                {payload.payload_state === 'expired'
                    ? 'This payload has expired. Its scores and summaries are still available.'
                    : payload.payload_state === 'not_provided'
                      ? 'No payload was provided for this record.'
                      : 'This payload is currently unavailable.'}
            </p>
        )
    }
    return (
        <div className="@container">
            <div className="grid grid-cols-1 items-start gap-3 @min-[40rem]:grid-cols-2">
                {fields.map((field) => {
                    const data = payload.data as Record<string, unknown>
                    const present = Object.prototype.hasOwnProperty.call(data, field)
                    const value = data[field]
                    if (!present && (field === 'reasoning' || field === 'error_message' || field === 'metadata')) {
                        return null
                    }
                    const label = field.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
                    const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
                    const initiallyCollapsed =
                        field === 'metadata' || (text && (text.length > 1200 || text.split('\n').length > 12))
                    const content = (
                        <div className="min-w-0">
                            {!present ? (
                                <span className="text-muted">Not provided</span>
                            ) : typeof value === 'object' && value !== null ? (
                                <HighlightedJSONViewer
                                    src={value}
                                    collapsed={2}
                                    collapseStringsAfterLength={300}
                                    groupArraysAfterLength={20}
                                    name={null}
                                />
                            ) : (
                                <div className="whitespace-pre-wrap break-words text-sm leading-relaxed" translate="no">
                                    {typeof value === 'string' ? value : JSON.stringify(value)}
                                </div>
                            )}
                        </div>
                    )
                    return (
                        <LemonCollapse
                            key={field}
                            defaultActiveKey={initiallyCollapsed ? undefined : field}
                            size="small"
                            className={cn(
                                'min-w-0 bg-surface-primary',
                                (field === 'reasoning' || field === 'error_message' || field === 'metadata') &&
                                    'col-span-full'
                            )}
                            panels={[
                                {
                                    key: field,
                                    header: { children: label, className: '!bg-surface-tertiary font-semibold' },
                                    content,
                                },
                            ]}
                        />
                    )
                })}
            </div>
        </div>
    )
}
