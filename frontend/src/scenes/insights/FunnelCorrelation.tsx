import { Card } from 'antd'
import { useValues, kea } from 'kea'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from './insightLogic'
import WarningOutlined from '@ant-design/icons/lib/icons/WarningOutlined'

import { FunnelCorrelationTable } from './InsightTabs/FunnelTab/FunnelCorrelationTable'
import { FunnelPropertyCorrelationTable } from './InsightTabs/FunnelTab/FunnelPropertyCorrelationTable'
import { FunnelStep } from '~/types'

const funnelCorrelationLogic = kea({
    connect: {
        // pull in values from `funnelLogic`
        values: [funnelLogic, ['stepsWithCount']],
    },

    selectors: ({ selectors }) => ({
        isSkewed: [
            () => [selectors.stepsWithCount],
            (stepsWithCount: FunnelStep[]) => {
                if (stepsWithCount?.length) {
                    const totalPeople = stepsWithCount[0].count
                    const successfulPeople = stepsWithCount.slice(-1)[0].count
                    return successfulPeople < totalPeople / 10 || successfulPeople > (totalPeople * 9) / 10
                }
                return false
            },
        ],
    }),
})

const useIsSkewed = (): boolean => {
    const { insightProps } = useValues(insightLogic)
    const { isSkewed } = useValues(funnelCorrelationLogic(insightProps))
    return isSkewed
}

export const FunnelCorrelation = (): JSX.Element => {
    const skewed = useIsSkewed()

    return (
        <>
            {skewed ? (
                <Card style={{ marginTop: '1em' }}>
                    <div style={{ display: 'flex' }}>
                        <div style={{ flexGrow: 1, display: 'flex', alignItems: 'center' }}>
                            <WarningOutlined className="text-warning" style={{ paddingRight: 8 }} />
                            <b>Funnel skewed!</b>
                            Your funnel has a large skew to either successes or failures. With such funnels it's hard to
                            get meaningful odds for events and property correlations. Try adjusting your funnel to have
                            a more balanced success/failure ratio.
                        </div>
                    </div>
                </Card>
            ) : null}

            <FunnelCorrelationTable />
            <FunnelPropertyCorrelationTable />
        </>
    )
}
