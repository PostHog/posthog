import React from 'react'
import { useValues } from 'kea'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonTable } from 'lib/components/LemonTable'

export function FunnelStepsTable(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { insightLoading } = useValues(logic)

    return <LemonTable dataSource={[]} columns={[]} loading={insightLoading} />
}
