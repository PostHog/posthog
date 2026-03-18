import { createContext, useContext } from 'react'

/**
 * Context for providing the current trace ID to nested message components.
 *
 * The trace ID comes from the human message that initiates a request,
 * and all subsequent AI messages in that exchange share the same trace ID.
 */
const TraceIdContext = createContext<string | undefined>(undefined)

export const TraceIdProvider = TraceIdContext.Provider

export function useTraceId(): string | undefined {
    return useContext(TraceIdContext)
}
