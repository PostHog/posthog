import { surveyResultsSamplePayload } from '../../components/WidgetCard/widgetOverviewStoryFixtures'

export function SurveyResultsWidgetPreview(): JSX.Element {
    const survey = surveyResultsSamplePayload.survey
    const rates = surveyResultsSamplePayload.rates
    const stats = surveyResultsSamplePayload.stats

    return (
        <div className="pointer-events-none flex flex-col gap-2 p-2 shadow-sm">
            <div className="flex items-center justify-between gap-2">
                <span className="truncate font-semibold">{survey.name}</span>
                <span className="rounded-full bg-success/10 px-2 py-0.5 text-xs font-semibold text-success">Active</span>
            </div>
            <div className="flex items-stretch rounded border bg-bg-light/40">
                {[
                    { title: 'Shown', value: stats['survey shown'].total_count },
                    { title: 'Responses', value: stats['survey sent'].total_count },
                    { title: 'Conversion', value: `${rates.response_rate}%` },
                ].map((item, index) => (
                    <div
                        key={item.title}
                        className={`flex flex-1 flex-col items-center px-2 py-1.5 text-center ${
                            index > 0 ? 'border-l border-border' : ''
                        }`}
                    >
                        <div className="text-2xs font-semibold uppercase tracking-wide text-muted">{item.title}</div>
                        <div className="text-lg font-semibold leading-tight">{item.value}</div>
                    </div>
                ))}
            </div>
        </div>
    )
}
