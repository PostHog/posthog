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
        <div className={`border rounded bg-surface-primary overflow-hidden ${className}`}>
            <div className="p-3">
                <div className="text-sm font-medium mb-1 max-h-20 overflow-y-auto">
                    {typeof response !== 'string' ? JSON.stringify(response) : response}
                </div>
                {showCount && (
                    <div className="text-xs text-muted-foreground">
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
                <div className="bg-surface-secondary px-3 py-2 border-t">
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
