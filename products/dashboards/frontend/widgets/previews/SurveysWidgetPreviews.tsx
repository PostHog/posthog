// Inline sample data keeps this preview off widgetOverviewStoryFixtures, which would import the
// widget catalog back and form a dependency cycle.
const SAMPLE_SURVEY = {
    name: 'Post-purchase feedback',
    shown: 1840,
    responses: 420,
    conversionRate: 22.83,
}

const SAMPLE_QUESTION = 'How was your checkout experience?'
const SAMPLE_RESPONSES = [
    { person: 'jordan@acme.com', answer: 'Fast and easy, no complaints!' },
    { person: 'sam@example.com', answer: 'Wish there were more payment options.' },
]

export function SurveyResultsWidgetPreview(): JSX.Element {
    return (
        <div className="pointer-events-none flex flex-col gap-2 p-2 shadow-sm">
            <div className="flex items-center justify-between gap-2">
                <span className="truncate font-semibold">{SAMPLE_SURVEY.name}</span>
                <span className="rounded-full bg-success/10 px-2 py-0.5 text-xs font-semibold text-success">
                    Active
                </span>
            </div>
            <div className="flex items-stretch rounded border bg-bg-light/40">
                {[
                    { title: 'Shown', value: SAMPLE_SURVEY.shown },
                    { title: 'Responses', value: SAMPLE_SURVEY.responses },
                    { title: 'Conversion', value: `${SAMPLE_SURVEY.conversionRate}%` },
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
            <div className="flex flex-col gap-2">
                <h5 className="m-0 text-2xs font-semibold uppercase tracking-wide text-muted">Recent responses</h5>
                {SAMPLE_RESPONSES.map((response) => (
                    <div key={response.person} className="flex flex-col gap-1 rounded border p-2">
                        <span className="truncate text-xs font-medium text-primary">{response.person}</span>
                        <span className="text-xs text-muted">Q: {SAMPLE_QUESTION}</span>
                        <span className="text-sm text-primary">{response.answer}</span>
                    </div>
                ))}
            </div>
        </div>
    )
}
