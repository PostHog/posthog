import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { AIObservabilityInstrumentationCheckEnumApi } from './generated/api.schemas'
import { useInstrumentationWarning } from './hooks/useInstrumentationEmptyState'

export function AIObservabilitySessionsEmptyState(): JSX.Element {
    const warning = useInstrumentationWarning(AIObservabilityInstrumentationCheckEnumApi.Sessions)

    if (!warning) {
        return <div className="p-4 text-center text-sm text-secondary">No sessions yet</div>
    }

    return (
        <EmptyMessage
            title="Traces are not grouped into sessions"
            description={warning.detail}
            buttonText="Learn more"
            buttonTo={warning.docs_url}
            buttonDataAttr="llma-sessions-instrumentation-docs"
            size="small"
        />
    )
}
