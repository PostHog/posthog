import { urls } from 'scenes/urls'

import { LLMTrace, LLMTracePerson } from '~/queries/schema/schema-general'

import { TraceSummaryBarProps } from '../components/TraceSummaryBar'
import { readString } from './propertyReaders'
import { traceStats } from './toTraceTree'

export function personLabel(trace: LLMTrace, person: LLMTracePerson | null): string {
    const properties = person?.properties ?? {}
    return readString(properties.email) ?? readString(properties.name) ?? trace.distinctId
}

export function toSummary(trace: LLMTrace, person: LLMTracePerson | null): TraceSummaryBarProps {
    return {
        traceId: trace.id,
        timestamp: trace.createdAt,
        person: trace.distinctId
            ? { label: personLabel(trace, person), href: urls.personByDistinctId(trace.distinctId) }
            : null,
        totals: traceStats(trace),
    }
}
