import { llmAnalyticsTracesSampleTraces } from '../llm_analytics/llmAnalyticsTracesSampleData'
import { LlmAnalyticsTracesWidgetRow } from '../llm_analytics/LlmAnalyticsTracesWidgetRow'

export function LlmAnalyticsTracesWidgetPreview(): JSX.Element {
    return (
        <div className="flex flex-col divide-y divide-border shadow-sm">
            {llmAnalyticsTracesSampleTraces.map((trace) => (
                <LlmAnalyticsTracesWidgetRow key={trace.id} trace={trace} />
            ))}
        </div>
    )
}
