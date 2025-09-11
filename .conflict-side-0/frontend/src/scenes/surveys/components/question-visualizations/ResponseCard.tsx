import { TZLabel } from 'lib/components/TZLabel'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

interface ResponseCardProps {
    response: string
    distinctId?: string
    personProperties?: Record<string, any>
    timestamp?: string
    count?: number
    className?: string
}

export function ScrollToSurveyResultsCard({ numOfResponses }: { numOfResponses: number }): JSX.Element {
    return (
        <button
            className="border rounded p-3 bg-surface-primary flex items-center justify-center text-sm text-muted-foreground cursor-pointer"
            onClick={() => {
                const surveyTableResults = document.querySelector('.survey-table-results')
                if (surveyTableResults) {
                    surveyTableResults.scrollIntoView({ behavior: 'smooth' })
                }
            }}
        >
            <div className="text-center">
                <div className="font-medium">+{numOfResponses} more responses</div>
                <div className="text-xs mt-1">Click to see all of them</div>
            </div>
        </button>
    )
}

export function ResponseCard({
    response,
    distinctId,
    personProperties,
    timestamp,
    count,
    className = '',
}: ResponseCardProps): JSX.Element {
    const hasPersonData = distinctId !== undefined
    const showCount = count !== undefined && count > 1

    return (
        <div className={`border rounded bg-surface-primary overflow-hidden flex flex-col ${className}`}>
            <div className="p-3">
                <div className="text-sm font-medium mb-1 max-h-20 overflow-y-auto">
                    {typeof response !== 'string' ? JSON.stringify(response) : response}
                </div>
                {showCount && timestamp && (
                    <div className="text-xs text-secondary flex items-center gap-1">
                        {count} responses • last response <TZLabel time={timestamp} className="border-none" />
                    </div>
                )}
                {showCount && !timestamp && (
                    <div className="text-xs text-secondary">
                        {count} response{count !== 1 ? 's' : ''}
                    </div>
                )}
                {timestamp && !showCount && (
                    <div className="text-xs text-secondary">
                        <TZLabel time={timestamp} />
                    </div>
                )}
            </div>
            {hasPersonData && (
                <div className="bg-surface-secondary px-3 py-2 border-t flex flex-1 justify-center flex-col">
                    {showCount && <div className="text-xs text-secondary mb-1">Last respondent:</div>}
                    <PersonDisplay
                        person={{
                            distinct_id: distinctId,
                            properties: personProperties || {},
                        }}
                        withIcon={true}
                        noEllipsis={false}
                        isCentered={false}
                    />
                </div>
            )}
        </div>
    )
}
