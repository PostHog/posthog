import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ExperimentMetric } from '~/queries/schema/schema-general'

interface MetricErrorStateProps {
    error: {
        detail: string | object | any
        statusCode?: number
        queryId?: string
    }
    metric: ExperimentMetric
    query?: Record<string, any>
    onRetry?: () => void
    height?: number
}

/**
 * Parse error message that may be in ErrorDetail string format.
 * Backend sometimes serializes ValidationError.detail as a string like:
 * "[ErrorDetail(string='Message', code='code')]"
 */
function parseErrorMessage(error: MetricErrorStateProps['error']): string {
    const errorDetail = error.detail

    if (typeof errorDetail === 'string') {
        // Try to match list format: [ErrorDetail(string='...', code='...')]
        const listMatch = errorDetail.match(/\[ErrorDetail\(string='([^']*)',\s*code='([^']*)'\)\]/)
        if (listMatch) {
            return listMatch[1]
        }

        // Try to match single format: ErrorDetail(string='...', code='...')
        const singleMatch = errorDetail.match(/ErrorDetail\(string='([^']*)',\s*code='([^']*)'\)/)
        if (singleMatch) {
            return singleMatch[1]
        }

        return errorDetail
    }

    if (typeof errorDetail === 'object' && errorDetail !== null) {
        // If it's an object, try to extract message or detail field
        return (errorDetail as any).message || (errorDetail as any).detail || JSON.stringify(errorDetail)
    }

    return 'An error occurred while loading metric results'
}

export function MetricErrorState({ error, query, onRetry, height = 200 }: MetricErrorStateProps): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    const errorMessage = parseErrorMessage(error)
    const isTimeout = error.statusCode === 504

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="flex flex-col items-center justify-center gap-1" style={{ minHeight: `${height}px` }}>
            <div className="flex items-center justify-center">
                <IconErrorOutline className="text-sm text-danger" />
                <h4 className="text-sm text-danger font-semibold m-0 ml-2">
                    {isTimeout ? 'Experiment results timed out' : 'Error loading metric results'}
                </h4>
            </div>
            <p className="text-xs text-muted max-w-80 text-center m-0">
                {isTimeout
                    ? 'This may occur when the experiment has a large amount of data or is particularly complex. We are actively working on fixing this. In the meantime, please click try again to refresh the results.'
                    : errorMessage}
            </p>

            <div className="flex gap-1.5 mt-1">
                {onRetry && (
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        onClick={onRetry}
                        sideAction={
                            query
                                ? {
                                      dropdown: {
                                          overlay: (
                                              <LemonMenuOverlay
                                                  items={[
                                                      {
                                                          label: 'Open in query debugger',
                                                          to: urls.debugQuery(query),
                                                      },
                                                  ]}
                                              />
                                          ),
                                          placement: 'bottom-end' as const,
                                      },
                                  }
                                : undefined
                        }
                    >
                        Try again
                    </LemonButton>
                )}

                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={() =>
                        openSupportForm({
                            kind: 'bug',
                            target_area: 'experiments',
                        })
                    }
                >
                    Report issue
                </LemonButton>
            </div>

            {error.queryId && (
                <div className="text-[10px] text-muted mt-1">
                    Query ID: <span className="font-mono">{error.queryId}</span>
                </div>
            )}
        </div>
    )
}
