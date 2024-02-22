import './CorrelationMatrix.scss'

import { Button, Modal } from 'antd'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import {
    IconCancel,
    IconCheckCircleOutline,
    IconErrorOutline,
    IconTrendingFlat,
    IconTrendingFlatDown,
} from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, percentage, pluralize } from 'lib/utils'
import { funnelCorrelationDetailsLogic } from 'scenes/funnels/funnelCorrelationDetailsLogic'
import { funnelCorrelationLogic } from 'scenes/funnels/funnelCorrelationLogic'
import { funnelPersonsModalLogic } from 'scenes/funnels/funnelPersonsModalLogic'
import { parseDisplayNameForCorrelation } from 'scenes/funnels/funnelUtils'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelCorrelationResultsType, FunnelCorrelationType } from '~/types'

export function CorrelationMatrix(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { correlationsLoading } = useValues(funnelCorrelationLogic(insightProps))
    const { funnelCorrelationDetails, correlationMatrixAndScore } = useValues(
        funnelCorrelationDetailsLogic(insightProps)
    )
    const { setFunnelCorrelationDetails } = useActions(funnelCorrelationDetailsLogic(insightProps))
    const { openCorrelationPersonsModal } = useActions(funnelPersonsModalLogic(insightProps))

    const actor = funnelCorrelationDetails?.result_type === FunnelCorrelationResultsType.Events ? 'event' : 'property'
    const action =
        funnelCorrelationDetails?.result_type === FunnelCorrelationResultsType.Events
            ? 'performed event'
            : 'have property'

    let displayName = <></>

    if (funnelCorrelationDetails) {
        const { first_value, second_value } = parseDisplayNameForCorrelation(funnelCorrelationDetails)
        displayName = (
            <>
                <PropertyKeyInfo value={first_value} />
                {second_value !== undefined && (
                    <>
                        {' :: '}
                        <PropertyKeyInfo value={second_value} disablePopover />
                    </>
                )}
            </>
        )
    }

    const { correlationScore, truePositive, falsePositive, trueNegative, falseNegative, correlationScoreStrength } =
        correlationMatrixAndScore

    const scoreIcon =
        correlationScoreStrength === 'strong' ? (
            <IconCheckCircleOutline className="text-success" />
        ) : correlationScoreStrength === 'moderate' ? (
            <IconCancel className="text-warning" />
        ) : (
            <IconErrorOutline className="text-danger" />
        )

    const dismiss = (): void => setFunnelCorrelationDetails(null)

    return (
        <Modal
            className="correlation-matrix"
            visible={!!funnelCorrelationDetails}
            onCancel={dismiss}
            destroyOnClose
            footer={<Button onClick={dismiss}>Dismiss</Button>}
            width={600}
            title="Correlation details"
        >
            <div className="correlation-table-wrapper">
                {correlationsLoading ? (
                    <div className="mt-4 text-center">
                        <Spinner className="text-4xl" />
                    </div>
                ) : funnelCorrelationDetails ? (
                    <>
                        <p className="text-muted-alt mb-4">
                            The table below displays the correlation details for users who {action} <b>{displayName}</b>
                            .
                        </p>
                        <table>
                            <thead>
                                <tr className="table-title">
                                    <td colSpan={3}>Results matrix</td>
                                </tr>
                                <tr>
                                    <td>
                                        {funnelCorrelationDetails?.result_type === FunnelCorrelationResultsType.Events
                                            ? 'Performed event'
                                            : 'Has property'}
                                    </td>
                                    <td>Success</td>
                                    <td>Dropped off</td>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td className="horizontal-header">Yes</td>
                                    <td>
                                        <Tooltip
                                            title={`True positive (TP) - Percentage of users who ${action} and completed the funnel.`}
                                        >
                                            <div className="percentage">
                                                {truePositive
                                                    ? percentage(truePositive / (truePositive + falsePositive))
                                                    : '0.00%'}
                                            </div>
                                        </Tooltip>
                                        {truePositive === 0 ? (
                                            '0 users'
                                        ) : (
                                            <Link
                                                onClick={() => {
                                                    openCorrelationPersonsModal(funnelCorrelationDetails, true)
                                                }}
                                            >
                                                {pluralize(truePositive, 'user', undefined, true)}
                                            </Link>
                                        )}
                                    </td>
                                    <td>
                                        <Tooltip
                                            title={`False negative (FN) - Percentage of users who ${action} and did not complete the funnel.`}
                                        >
                                            <div className="percentage">
                                                {falseNegative
                                                    ? percentage(falseNegative / (falseNegative + trueNegative))
                                                    : '0.00%'}
                                            </div>
                                        </Tooltip>
                                        {falseNegative === 0 ? (
                                            '0 users'
                                        ) : (
                                            <Link
                                                onClick={() => {
                                                    openCorrelationPersonsModal(funnelCorrelationDetails, false)
                                                }}
                                            >
                                                {pluralize(falseNegative, 'user', undefined, true)}
                                            </Link>
                                        )}
                                    </td>
                                </tr>
                                <tr>
                                    <td className="horizontal-header">No</td>
                                    <td>
                                        <Tooltip
                                            title={`False positive (FP) - Percentage of users who did not ${action} and completed the funnel.`}
                                        >
                                            <div className="percentage">
                                                {falsePositive
                                                    ? percentage(falsePositive / (truePositive + falsePositive))
                                                    : '0.00%'}
                                            </div>
                                        </Tooltip>
                                        {pluralize(falsePositive, 'user', undefined, true)}
                                    </td>
                                    <td>
                                        <Tooltip
                                            title={`True negative (TN) - Percentage of users who did not ${action} and did not complete the funnel.`}
                                        >
                                            <div className="percentage">
                                                {trueNegative
                                                    ? percentage(trueNegative / (falseNegative + trueNegative))
                                                    : '0.00%'}
                                            </div>
                                        </Tooltip>
                                        {pluralize(trueNegative, 'user', undefined, true)}
                                    </td>
                                </tr>
                                <tr>
                                    <td className="horizontal-header" />
                                    <td>
                                        <b>100%</b>
                                    </td>
                                    <td>
                                        <b>100%</b>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                        <div className="mt-4 text-center">
                            {capitalizeFirstLetter(funnelCorrelationDetails?.result_type || '')} <b>{displayName}</b>{' '}
                            has a{' '}
                            {funnelCorrelationDetails?.correlation_type === FunnelCorrelationType.Success ? (
                                <Tooltip
                                    title={`Positive correlation means this ${actor} is correlated with a successful conversion.`}
                                >
                                    <span className="cursor-help text-success">
                                        <IconTrendingFlat /> positive correlation
                                    </span>
                                </Tooltip>
                            ) : (
                                <Tooltip
                                    title={`Negative correlation means this ${actor} is correlated with an unsuccessful conversion (user dropped off).`}
                                >
                                    <strong className="cursor-help text-danger">
                                        <IconTrendingFlatDown /> negative correlation
                                    </strong>
                                </Tooltip>
                            )}{' '}
                            score of{' '}
                            <Tooltip title={`This ${actor} has ${correlationScoreStrength} correlation.`}>
                                <strong
                                    className={clsx(
                                        'cursor-help',
                                        correlationScoreStrength === 'strong'
                                            ? 'text-success'
                                            : correlationScoreStrength === 'moderate'
                                            ? 'text-warning'
                                            : 'text-danger'
                                    )}
                                >
                                    {scoreIcon} {correlationScore.toFixed(3)}
                                </strong>
                            </Tooltip>
                        </div>
                    </>
                ) : (
                    <LemonBanner type="error">
                        We could not load the details for this correlation value. Please recreate your funnel and try
                        again.
                    </LemonBanner>
                )}
            </div>
        </Modal>
    )
}
