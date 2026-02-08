import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { parseErrorMessage } from '~/queries/query'
import { ExperimentMetric } from '~/queries/schema/schema-general'

type MetricErrorStateProps = {
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

export const MetricErrorState = ({ error, query, onRetry, height = 200 }: MetricErrorStateProps): JSX.Element => {
    const { openSupportForm } = useActions(supportLogic)

    const errorMessage = parseErrorMessage(error.detail)
    const { message } = errorMessage

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
                    : message}
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
