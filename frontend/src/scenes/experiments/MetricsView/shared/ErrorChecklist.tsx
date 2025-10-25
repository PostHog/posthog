import { useValues } from 'kea'
import { combineUrl } from 'kea-router/lib/utils'

import { IconCheck, IconX } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { ActivityTab, InsightType } from '~/types'

import { experimentLogic } from '../../experimentLogic'

export enum ResultErrorCode {
    NO_CONTROL_VARIANT = 'no-control-variant',
    NO_TEST_VARIANT = 'no-test-variant',
    NO_EXPOSURES = 'no-exposures',
}

export function ErrorChecklist({ error, metric }: { error: any; metric: any }): JSX.Element {
    const { experiment, variants, getInsightType } = useValues(experimentLogic)

    if (!error) {
        return <></>
    }

    const { statusCode, hasDiagnostics } = error

    function ChecklistItem({ errorCode, value }: { errorCode: ResultErrorCode; value: boolean }): JSX.Element {
        const failureText: Record<ResultErrorCode, string> = {
            [ResultErrorCode.NO_CONTROL_VARIANT]: 'Events with the control variant not received',
            [ResultErrorCode.NO_TEST_VARIANT]: 'Events with at least one test variant not received',
            [ResultErrorCode.NO_EXPOSURES]: 'Exposure events not received',
        }

        const successText: Record<ResultErrorCode, string> = {
            [ResultErrorCode.NO_CONTROL_VARIANT]: 'Events with the control variant received',
            [ResultErrorCode.NO_TEST_VARIANT]: 'Events with at least one test variant received',
            [ResultErrorCode.NO_EXPOSURES]: 'Exposure events have been received',
        }

        const insightType = getInsightType(metric)
        const hasMissingExposure = errorCode === ResultErrorCode.NO_EXPOSURES

        const requiredEvent =
            insightType === InsightType.TRENDS
                ? hasMissingExposure
                    ? metric.exposure_query?.series[0]?.event || '$feature_flag_called'
                    : metric.count_query?.series[0]?.event
                : metric.funnels_query?.series[0]?.event

        const query = {
            kind: NodeKind.DataTableNode,
            full: true,
            source: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', `properties."$feature/${experiment.feature_flag?.key}"`, 'timestamp'],
                orderBy: ['timestamp DESC'],
                after: experiment.start_date,
                event: requiredEvent,
                properties: [
                    {
                        key: `$feature/${experiment.feature_flag?.key}`,
                        value: hasMissingExposure
                            ? variants.map((variant) => variant.key)
                            : errorCode === ResultErrorCode.NO_CONTROL_VARIANT
                              ? ['control']
                              : variants.slice(1).map((variant) => variant.key),
                        operator: 'exact',
                        type: 'event',
                    },
                    ...(hasMissingExposure
                        ? [
                              {
                                  key: '$feature_flag',
                                  value: [experiment.feature_flag?.key],
                                  operator: 'exact',
                                  type: 'event',
                              },
                          ]
                        : []),
                ],
                filterTestAccounts: metric.count_query?.filter_test_accounts,
            },
            propertiesViaUrl: true,
            showPersistentColumnConfigurator: true,
        }

        return (
            <div className="flex items-center deprecated-space-x-2">
                {value === false ? (
                    <span className="flex items-center deprecated-space-x-2">
                        <IconCheck className="text-success" fontSize={16} />
                        <span className="text-secondary">{successText[errorCode]}</span>
                    </span>
                ) : (
                    <span className="flex items-center deprecated-space-x-2">
                        <IconX className="text-danger" fontSize={16} />
                        <span>{failureText[errorCode]}</span>
                        <Tooltip title="Verify missing events in the Activity tab">
                            <Link
                                target="_blank"
                                className="font-semibold"
                                to={combineUrl(urls.activity(ActivityTab.ExploreEvents), {}, { q: query }).url}
                            >
                                <IconOpenInNew fontSize="16" className="-ml-1" />
                            </Link>
                        </Tooltip>
                    </span>
                )}
            </div>
        )
    }

    if (hasDiagnostics) {
        const checklistItems = []
        for (const [errorCode, value] of Object.entries(error.detail as Record<ResultErrorCode, boolean>)) {
            // Check if the error code is valid (cached response might still have old error codes)
            if (!Object.values(ResultErrorCode).includes(errorCode as ResultErrorCode)) {
                continue
            }
            checklistItems.push(
                <ChecklistItem key={errorCode} errorCode={errorCode as ResultErrorCode} value={value} />
            )
        }

        return <div>{checklistItems}</div>
    }

    if (statusCode === 504) {
        return (
            <>
                <h2 className="text-xl font-semibold leading-tight">Experiment results timed out</h2>
                <div className="text-sm text-center text-balance">
                    This may occur when the experiment has a large amount of data or is particularly complex. We are
                    actively working on fixing this. In the meantime, please try refreshing the experiment to retrieve
                    the results.
                </div>
            </>
        )
    }

    // Other unexpected errors
    return <div>{error.detail}</div>
}
