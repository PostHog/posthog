import { Button, Modal } from 'antd'
import React from 'react'
import { CheckCircleFilled, InfoCircleOutlined, MinusCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import './CorrelationMatrix.scss'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { capitalizeFirstLetter, percentage, pluralize } from 'lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Link } from 'lib/components/Link'
import { Tooltip } from 'lib/components/Tooltip'
import { FunnelCorrelationResultsType, FunnelCorrelationType } from '~/types'
import { InlineMessage } from 'lib/components/InlineMessage/InlineMessage'

export function CorrelationMatrix(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { correlationsLoading, funnelCorrelationDetails, parseDisplayNameForCorrelation, correlationMatrixAndScore } =
        useValues(logic)
    const { setFunnelCorrelationDetails, openCorrelationPersonsModal } = useActions(logic)

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
            <CheckCircleFilled style={{ color: 'var(--success)' }} />
        ) : correlationScoreStrength === 'moderate' ? (
            <MinusCircleOutlined style={{ color: 'var(--warning)' }} />
        ) : (
            <CloseCircleOutlined style={{ color: 'var(--danger)' }} />
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
                    <div className="mt text-center">
                        <Spinner size="lg" />
                    </div>
                ) : funnelCorrelationDetails ? (
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
                                        <div className="percentage">
                                            <Tooltip
                                                title={`False negative (FN) - Percentage of users who ${action} and did not complete the funnel.`}
                                            >
                                                {falseNegative
                                                    ? percentage(falseNegative / (falseNegative + trueNegative))
                                                    : '0.00%'}
                                            </Tooltip>
                                        </div>
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
                                        <div className="percentage">
                                            <Tooltip
                                                title={`False positive (FP) - Percentage of users who did not ${action} and completed the funnel.`}
                                            >
                                                {falsePositive
                                                    ? percentage(falsePositive / (truePositive + falsePositive))
                                                    : '0.00%'}
                                            </Tooltip>
                                        </div>
                                        {pluralize(falsePositive, 'user', undefined, true)}
                                    </td>
                                    <td>
                                        <div className="percentage">
                                            <Tooltip
                                                title={`True negative (TN) - Percentage of users who did not ${action} and did not complete the funnel.`}
                                            >
                                                {trueNegative
                                                    ? percentage(trueNegative / (falseNegative + trueNegative))
                                                    : '0.00%'}
                                            </Tooltip>
                                        </div>
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
                        <div className="mt text-center">
                            {capitalizeFirstLetter(funnelCorrelationDetails?.result_type || '')} <b>{displayName}</b>{' '}
                            has a{' '}
                            {funnelCorrelationDetails?.correlation_type === FunnelCorrelationType.Success ? (
                                <b className="text-success">
                                    positive{' '}
                                    <Tooltip
                                        title={`Positive correlation means this ${actor} is correlated with a successful conversion.`}
                                    >
                                        <InfoCircleOutlined className="cursor-pointer" />
                                    </Tooltip>
                                </b>
                            ) : (
                                <b className="text-danger">
                                    negative{' '}
                                    <Tooltip
                                        title={`Negative correlation means this ${actor} is correlated with an unsuccessful conversion (user dropped off).`}
                                    >
                                        <InfoCircleOutlined className="cursor-pointer" />
                                    </Tooltip>
                                </b>
                            )}{' '}
                            correlation score of{' '}
                            <b
                                style={{
                                    color:
                                        correlationScoreStrength === 'strong'
                                            ? 'var(--success)'
                                            : correlationScoreStrength === 'moderate'
                                            ? 'var(--warning)'
                                            : 'var(--danger)',
                                }}
                            >
                                <Tooltip title={`This ${actor} has ${correlationScoreStrength} correlation.`}>
                                    <span style={{ cursor: 'pointer' }}>
                                        {scoreIcon} {correlationScore.toFixed(3)}
                                    </span>
                                </Tooltip>
                            </b>
                        </div>
                    </>
                ) : (
                    <div>
                        <InlineMessage type="danger">
                            We could not load the details for this correlation value. Please recreate your funnel and
                            try again.
                        </InlineMessage>
                    </div>
                )}
            </div>
        </Modal>
    )
}
