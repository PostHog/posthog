import React, { useState } from 'react'
import { AddToDashboardModal, SaveToDashboardModal } from './SaveToDashboardModal'
import { InsightModel } from '~/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { useValues } from 'kea'
import { urls } from '../../../scenes/urls'
import { LemonButton } from '../LemonButton'
import { IconGauge, IconWithCount } from 'lib/components/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

interface SaveToDashboardProps {
    insight: Partial<InsightModel>
    canEditInsight: boolean
}

export function SaveToDashboard({ insight, canEditInsight }: SaveToDashboardProps): JSX.Element {
    const [openModal, setOpenModal] = useState<boolean>(false)
    const { rawDashboards } = useValues(dashboardsModel)
    const dashboards = insight.dashboards?.map((dashboard) => rawDashboards[dashboard]).filter((d) => !!d) || []

    const { featureFlags } = useValues(featureFlagLogic)
    const multiDashboardInsights = featureFlags[FEATURE_FLAGS.MULTI_DASHBOARD_INSIGHTS]

    return (
        <span className="save-to-dashboard" data-attr="save-to-dashboard-button">
            {multiDashboardInsights ? (
                <>
                    <AddToDashboardModal
                        visible={openModal}
                        closeModal={() => setOpenModal(false)}
                        insight={insight}
                        canEditInsight={canEditInsight}
                    />
                    <LemonButton
                        onClick={() => setOpenModal(true)}
                        type="secondary"
                        icon={
                            <IconWithCount count={dashboards.length} showZero={false}>
                                <IconGauge />
                            </IconWithCount>
                        }
                    >
                        Add to dashboard
                    </LemonButton>
                </>
            ) : (
                <>
                    <SaveToDashboardModal
                        visible={openModal}
                        closeModal={() => setOpenModal(false)}
                        insight={insight}
                        canEditInsight={canEditInsight}
                    />
                    {dashboards.length > 0 ? (
                        <LemonButton
                            disabled={!canEditInsight}
                            to={urls.dashboard(dashboards[0].id, insight.short_id)}
                            type="secondary"
                            icon={<IconGauge />}
                        >
                            {dashboards.length > 1 ? 'On multiple dashboards' : `On dashboard: ${dashboards[0]?.name}`}
                        </LemonButton>
                    ) : (
                        <LemonButton
                            disabled={!canEditInsight}
                            onClick={() => setOpenModal(true)}
                            type="secondary"
                            icon={<IconGauge />}
                        >
                            Add to dashboard
                        </LemonButton>
                    )}
                </>
            )}
        </span>
    )
}
