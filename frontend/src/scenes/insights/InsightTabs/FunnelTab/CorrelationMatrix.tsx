import { Button, Modal, Skeleton } from 'antd'
import React from 'react'
import { CheckCircleFilled } from '@ant-design/icons'
import './CorrelationMatrix.scss'
import { useActions, useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export function CorrelationMatrix(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { filters } = useValues(logic)
    const { setFilters } = useActions(logic)

    const correlationsLoading = true

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
                        <Skeleton active />
                    </div>
                ) : (
                    <>
                        <p className="text-muted-alt mb">
                            The table below displays the correlation details for users with the property{' '}
                            <b>Initial Device Type :: Desktop</b>.
                        </p>
                        <table>
                            <thead>
                                <tr className="table-title">
                                    <td colSpan={3}>Results matrix</td>
                                </tr>
                                <tr>
                                    <td>Has property</td>
                                    <td>Success</td>
                                    <td>Dropped off</td>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td className="horizontal-header">Yes</td>
                                    <td>
                                        <div className="percentage">55.4%</div>2,373
                                    </td>
                                    <td>
                                        <div className="percentage">12.3%</div>1,209
                                    </td>
                                </tr>
                                <tr>
                                    <td className="horizontal-header">No</td>
                                    <td>
                                        <div className="percentage">55.4%</div>2,373
                                    </td>
                                    <td>
                                        <div className="percentage">12.3%</div>1,209
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                        <div className="mt text-center">
                            Property <b>Initial Device Type :: Desktop</b> has a correlation score of{' '}
                            <b style={{ color: 'var(--success)' }}>
                                <CheckCircleFilled /> 0.85
                            </b>
                        </div>
                    </>
                )}
            </div>
        </Modal>
    )
}
