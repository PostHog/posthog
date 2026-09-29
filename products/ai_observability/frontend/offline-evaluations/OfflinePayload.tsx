import { LemonCard } from '@posthog/lemon-ui'

import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'

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
            <div className="grid grid-cols-1 gap-4 @min-[40rem]:grid-cols-2">
                {fields.map((field) => {
                    const data = payload.data as Record<string, unknown>
                    const present = Object.prototype.hasOwnProperty.call(data, field)
                    const value = data[field]
                    return (
                        <LemonCard key={field} hoverEffect={false} className="min-w-0 p-3">
                            <h4 className="mb-2">
                                {field.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())}
                            </h4>
                            {!present ? (
                                <span className="text-muted">Not provided</span>
                            ) : typeof value === 'object' && value !== null ? (
                                <HighlightedJSONViewer src={value} collapsed={2} name={null} />
                            ) : (
                                <pre className="m-0 whitespace-pre-wrap break-words text-sm" translate="no">
                                    {JSON.stringify(value)}
                                </pre>
                            )}
                        </LemonCard>
                    )
                })}
            </div>
        </div>
    )
}
