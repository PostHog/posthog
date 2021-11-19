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

export function CorrelationMatrix(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { filters, correlationsLoading, correlationDetails, parseDisplayNameForCorrelation } = useValues(logic)
    const { setFilters } = useActions(logic)

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
    }

    const dismiss = (): void => {
        setFilters({ funnel_correlation_details: undefined })
    }

    return (
        <Modal
            className="correlation-matrix"
            visible={!!filters.funnel_correlation_details}
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
                            The table below displays the correlation details for users{' '}
                            {filters.funnel_correlation_details?.type === 'property'
                                ? 'who have property'
                                : 'who performed event'}{' '}
                            <b>{displayName}</b>.
                        </p>
                        <table>
                            <thead>
                                <tr className="table-title">
                                    <td colSpan={3}>Results matrix</td>
                                </tr>
                                <tr>
                                    <td>
                                        {filters.funnel_correlation_details?.type === 'property'
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
                                        <div className="percentage">
                                            {percentage(
                                                correlationDetails.success_count /
                                                    (correlationDetails.success_count +
                                                        correlationDetails.failure_count)
                                            ) || '0.00%'}
                                        </div>
                                        {/* TODO: Fix links to person modal */}
                                        {/* TODO: Handle zero users */}
                                        <Link to={correlationDetails.success_people_url}>
                                            {correlationDetails.success_count.toLocaleString()}{' '}
                                            {pluralize(correlationDetails.success_count, 'user', undefined, false)}
                                        </Link>
                                    </td>
                                    <td>
                                        <div className="percentage">
                                            {percentage(
                                                correlationDetails.failure_count /
                                                    (correlationDetails.success_count +
                                                        correlationDetails.failure_count)
                                            ) || '0.00%'}
                                        </div>
                                        <Link to={correlationDetails.failure_people_url}>
                                            {correlationDetails.failure_count.toLocaleString()}{' '}
                                            {pluralize(correlationDetails.failure_count, 'user', undefined, false)}
                                        </Link>
                                    </td>
                                </tr>
                                <tr>
                                    <td className="horizontal-header">No</td>
                                    <td>
                                        <div className="percentage">?%</div>???
                                    </td>
                                    <td>
                                        <div className="percentage">?%</div>???
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                        <div className="mt text-center">
                            {capitalizeFirstLetter(filters.funnel_correlation_details?.type || '')} <b>{displayName}</b>{' '}
                            has a correlation score of{' '}
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
