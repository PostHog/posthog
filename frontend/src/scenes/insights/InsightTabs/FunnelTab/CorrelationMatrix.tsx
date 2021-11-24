import { Button, Modal } from 'antd'
import React from 'react'
import { CheckCircleFilled } from '@ant-design/icons'
import './CorrelationMatrix.scss'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { capitalizeFirstLetter, percentage, pluralize } from 'lib/utils'
import { ErrorMessage } from 'lib/components/ErrorMessage/ErrorMessage'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Link } from 'lib/components/Link'
import { Tooltip } from 'lib/components/Tooltip'

export function CorrelationMatrix(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const {
        funnelCorrelationDetailsParams,
        correlationsLoading,
        correlationDetails,
        parseDisplayNameForCorrelation,
        steps,
    } = useValues(logic)
    const { setFunnelCorrelationDetailsParams } = useActions(logic)

    // TODO: Handle correlation with breakdown
    const successTotal = steps[steps.length - 1].count
    const failureTotal = steps[0].count - successTotal
    const action = funnelCorrelationDetailsParams?.type === 'property' ? 'have property' : 'performed event'
    let falsePositive = 0,
        trueNegative = 0

    let displayName = <></>

    if (correlationDetails) {
        const { first_value, second_value } = parseDisplayNameForCorrelation(correlationDetails)
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
        falsePositive = successTotal - correlationDetails.success_count
        trueNegative = failureTotal - correlationDetails.failure_count
    }

    const dismiss = (): void => {
        setFunnelCorrelationDetailsParams(null)
    }

    return (
        <Modal
            className="correlation-matrix"
            visible={!!funnelCorrelationDetailsParams}
            onCancel={dismiss}
            destroyOnClose
            footer={<Button onClick={dismiss}>Dismiss</Button>}
            width={600}
            title="Correlation details"
        >
            <div className="correlation-table-wrapper">
                {correlationsLoading ? (
                    <div className="mt text-center">
                        <Spinner size="lg" />
                    </div>
                ) : correlationDetails ? (
                    <>
                        <p className="text-muted-alt mb">
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
                                        {funnelCorrelationDetailsParams?.type === 'property'
                                            ? 'Has property'
                                            : 'Performed event'}
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
                                                {successTotal && correlationDetails.success_count
                                                    ? percentage(correlationDetails.success_count / successTotal)
                                                    : '0.00%'}
                                            </div>
                                        </Tooltip>
                                        {/* TODO: Fix links to person modal */}
                                        {correlationDetails.success_count === 0 ? (
                                            '0 users'
                                        ) : (
                                            <Link to={correlationDetails.success_people_url}>
                                                {pluralize(
                                                    correlationDetails.success_count,
                                                    'user',
                                                    undefined,
                                                    true,
                                                    true
                                                )}
                                            </Link>
                                        )}
                                    </td>
                                    <td>
                                        <div className="percentage">
                                            <Tooltip
                                                title={`False negative (FN) - Percentage of users who ${action} and did not complete the funnel.`}
                                            >
                                                {failureTotal && correlationDetails.failure_count
                                                    ? percentage(correlationDetails.failure_count / failureTotal)
                                                    : '0.00%'}
                                            </Tooltip>
                                        </div>
                                        {correlationDetails.failure_count === 0 ? (
                                            '0 users'
                                        ) : (
                                            <Link to={correlationDetails.failure_people_url}>
                                                {pluralize(
                                                    correlationDetails.failure_count,
                                                    'user',
                                                    undefined,
                                                    true,
                                                    true
                                                )}
                                            </Link>
                                        )}
                                    </td>
                                </tr>
                                <tr>
                                    <td className="horizontal-header">No</td>
                                    <td>
                                        <div className="percentage">
                                            <Tooltip
                                                title={`False positive (FP) - Percentage of users who did not ${action} and completed the funnel.`}
                                            >
                                                {successTotal && falsePositive
                                                    ? percentage(falsePositive / successTotal)
                                                    : '0.00%'}
                                            </Tooltip>
                                        </div>
                                        {pluralize(falsePositive, 'user', undefined, true, true)}
                                    </td>
                                    <td>
                                        <div className="percentage">
                                            <Tooltip
                                                title={`True negative (TN) - Percentage of users who did not ${action} and did not complete the funnel.`}
                                            >
                                                {failureTotal && trueNegative
                                                    ? percentage(trueNegative / failureTotal)
                                                    : '0.00%'}
                                            </Tooltip>
                                        </div>
                                        {pluralize(trueNegative, 'user', undefined, true, true)}
                                    </td>
                                </tr>
                                <tr>
                                    <td className="horizontal-header"></td>
                                    <td>
                                        <b>100%</b>
                                    </td>
                                    <td>
                                        <b>100%</b>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                        <div className="mt text-center">
                            {capitalizeFirstLetter(funnelCorrelationDetailsParams?.type || '')} <b>{displayName}</b> has
                            a correlation score of {/* TODO: Implement actual odds ratio */}
                            <b style={{ color: 'var(--success)' }}>
                                <CheckCircleFilled /> 0.85
                            </b>
                        </div>
                    </>
                ) : (
                    <div>
                        <ErrorMessage>
                            We could not load the details for this correlation value. Please recreate your funnel and
                            try again.
                        </ErrorMessage>
                    </div>
                )}
            </div>
        </Modal>
    )
}
