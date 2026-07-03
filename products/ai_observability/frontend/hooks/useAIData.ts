import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { aiObservabilityAIDataLogic } from '../aiObservabilityAIDataLogic'

export interface UseAIDataResult {
    input: unknown
    output: unknown
    tools: unknown
    isLoading: boolean
}

export interface EventData {
    uuid: string
    input: unknown
    output: unknown
    tools?: unknown
    traceId?: string
    timestamp?: string
}

export function useAIData(eventData: EventData | undefined): UseAIDataResult {
    const { aiDataCache, isEventLoading } = useValues(aiObservabilityAIDataLogic)
    const { loadAIDataForEvent } = useActions(aiObservabilityAIDataLogic)

    const eventId = eventData?.uuid
    const input = eventData?.input
    const output = eventData?.output
    const tools = eventData?.tools
    const traceId = eventData?.traceId
    const timestamp = eventData?.timestamp
    const cached = eventId ? aiDataCache[eventId] : undefined
    const loading = eventId ? isEventLoading(eventId) : false

    // Only fire the loader when a real fetch is possible and a heavy prop is missing.
    const canFetch = !!traceId && !!timestamp
    const shouldFetch = canFetch && (input == null || output == null)

    useEffect(() => {
        if (!eventId || cached || loading || !shouldFetch) {
            return
        }

        loadAIDataForEvent({
            eventId,
            input,
            output,
            tools,
            traceId,
            timestamp,
        })
    }, [cached, loading, canFetch, loadAIDataForEvent, eventId, input, output, tools, traceId, timestamp, shouldFetch])

    if (!eventId) {
        return {
            input,
            output,
            tools,
            isLoading: false,
        }
    }

    // When we can't fetch, fall back to whatever was passed in — there's nothing to wait for.
    return {
        input: cached?.input ?? input,
        output: cached?.output ?? output,
        tools: cached?.tools ?? tools,
        isLoading: shouldFetch && (loading || !cached),
    }
}
