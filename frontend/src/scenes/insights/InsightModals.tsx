import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import { areAlertsSupportedForInsight } from 'lib/components/Alerts/insightAlertsLogic'
import { EditAlertModal } from 'lib/components/Alerts/views/EditAlertModal'
import { ManageAlertsModal } from 'lib/components/Alerts/views/ManageAlertsModal'
import { SharingModal } from 'lib/components/Sharing/SharingModal'
import { SubscriptionsModal } from 'lib/components/Subscriptions/SubscriptionsModal'
import { TerraformExportModal } from 'lib/components/TerraformExporter/TerraformExportModal'
import { NewDashboardModal } from 'scenes/dashboard/NewDashboardModal'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { urls } from 'scenes/urls'

import { HogQLQuery, InsightQueryNode } from '~/queries/schema/schema-general'
import { InsightLogicProps, InsightShortId, ItemMode } from '~/types'

import { EndpointFromInsightModal } from 'products/endpoints/frontend/EndpointFromInsightModal'

import { insightModalsLogic } from './insightModalsLogic'

export function InsightModals({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element | null {
    const { hasDashboardItemId } = useValues(insightLogic(insightLogicProps))

    return (
        <>
            {hasDashboardItemId && (
                <>
                    <InsightSubscriptionsModalWrapper insightLogicProps={insightLogicProps} />
                    <InsightSharingModalWrapper insightLogicProps={insightLogicProps} />
                    <InsightAddToDashboardModalWrapper insightLogicProps={insightLogicProps} />
                    <InsightAlertsModals insightLogicProps={insightLogicProps} />
                    <NewDashboardModal />
                    <InsightEndpointModalWrapper insightLogicProps={insightLogicProps} />
                </>
            )}

            <InsightTerraformModalWrapper insightLogicProps={insightLogicProps} />
        </>
    )
}

function InsightSubscriptionsModalWrapper({
    insightLogicProps,
}: {
    insightLogicProps: InsightLogicProps
}): JSX.Element {
    const { insightMode, itemId } = useValues(insightSceneLogic)
    const { insight } = useValues(insightLogic(insightLogicProps))
    const { push } = useActions(router)

    return (
        <SubscriptionsModal
            data-attr="insight-subscriptions-modal"
            isOpen={insightMode === ItemMode.Subscriptions}
            closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
            insightShortId={insight.short_id}
            subscriptionId={typeof itemId === 'number' || itemId === 'new' ? itemId : null}
        />
    )
}

function InsightSharingModalWrapper({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)
    const theInsightLogic = insightLogic(insightLogicProps)
    const { insightProps, insight } = useValues(theInsightLogic)
    const { insightData } = useValues(insightDataLogic(insightProps))
    const { push } = useActions(router)

    return (
        <SharingModal
            data-attr="insight-sharing-modal"
            title="Insight sharing"
            isOpen={insightMode === ItemMode.Sharing}
            closeModal={() => push(urls.insightView(insight.short_id as InsightShortId))}
            insightShortId={insight.short_id}
            insight={insight}
            cachedResults={insightData}
            previewIframe
            userAccessLevel={insight.user_access_level}
        />
    )
}

function InsightAlertsModals({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const { insightMode, alertId } = useValues(insightSceneLogic)
    const { insightProps, insight } = useValues(insightLogic(insightLogicProps))
    const { query } = useValues(insightDataLogic(insightProps))
    const { push } = useActions(router)

    const canCreateAlertForInsight = areAlertsSupportedForInsight(query)

    return (
        <>
            {insightMode === ItemMode.Alerts && (
                <ManageAlertsModal
                    onClose={() => push(urls.insightView(insight.short_id as InsightShortId))}
                    isOpen={insightMode === ItemMode.Alerts}
                    insightLogicProps={insightLogicProps}
                    insightId={insight.id as number}
                    insightShortId={insight.short_id as InsightShortId}
                    canCreateAlertForInsight={canCreateAlertForInsight}
                />
            )}

            {!!alertId && insight.id && (
                <EditAlertModal
                    onClose={() => push(urls.insightAlerts(insight.short_id as InsightShortId))}
                    isOpen={!!alertId}
                    alertId={alertId === null || alertId === 'new' ? undefined : alertId}
                    insightShortId={insight.short_id as InsightShortId}
                    insightId={insight.id}
                    onEditSuccess={() => push(urls.insightAlerts(insight.short_id as InsightShortId))}
                    insightLogicProps={insightLogicProps}
                />
            )}
        </>
    )
}

function InsightAddToDashboardModalWrapper({
    insightLogicProps,
}: {
    insightLogicProps: InsightLogicProps
}): JSX.Element {
    const { insightProps, canEditInsight } = useValues(insightLogic(insightLogicProps))
    const theInsightModalsLogic = insightModalsLogic(insightLogicProps)
    const { isAddToDashboardModalOpen } = useValues(theInsightModalsLogic)
    const { closeAddToDashboardModal } = useActions(theInsightModalsLogic)

    return (
        <AddToDashboardModal
            data-attr="insight-add-to-dashboard-modal"
            isOpen={isAddToDashboardModalOpen}
            closeModal={closeAddToDashboardModal}
            insightProps={insightProps}
            canEditInsight={canEditInsight}
        />
    )
}

function InsightTerraformModalWrapper({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const theInsightLogic = insightLogic(insightLogicProps)
    const { insightProps, insight, derivedName } = useValues(theInsightLogic)
    const { query } = useValues(insightDataLogic(insightProps))
    const theInsightModalsLogic = insightModalsLogic(insightLogicProps)
    const { isTerraformModalOpen } = useValues(theInsightModalsLogic)
    const { closeTerraformModal } = useActions(theInsightModalsLogic)

    return (
        <TerraformExportModal
            data-attr="insight-terraform-modal"
            isOpen={isTerraformModalOpen}
            onClose={closeTerraformModal}
            resource={{ type: 'insight', data: { ...insight, query, derived_name: derivedName } }}
        />
    )
}

function InsightEndpointModalWrapper({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const theInsightLogic = insightLogic(insightLogicProps)
    const { insightProps, insight } = useValues(theInsightLogic)
    const { insightQuery } = useValues(insightDataLogic(insightProps))

    return (
        <EndpointFromInsightModal
            tabId={insightProps.tabId || ''}
            insightQuery={insightQuery as HogQLQuery | InsightQueryNode}
            insightShortId={insight.short_id}
        />
    )
}
