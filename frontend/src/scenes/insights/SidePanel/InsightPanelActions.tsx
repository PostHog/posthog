import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCode2, IconCopy, IconEndpoints, IconGraph, IconPencil, IconPeople } from '@posthog/icons'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { captureImageLogic } from 'lib/components/Scenes/InsightOrDashboard/captureImageLogic'
import { SceneAddToDashboardButton } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToDashboardButton'
import { SceneAddToNotebookDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToNotebookDropdownMenu'
import { SceneCopyImageButton } from 'lib/components/Scenes/InsightOrDashboard/SceneCopyImageButton'
import { SceneExportDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneExportDropdownMenu'
import { SceneAlertsButton } from 'lib/components/Scenes/SceneAlertsButton'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFavorite } from 'lib/components/Scenes/SceneFavorite'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { SceneShareButton } from 'lib/components/Scenes/SceneShareButton'
import { SceneSubscribeButton } from 'lib/components/Scenes/SceneSubscribeButton'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { INSIGHT_GRAPH_SELECTOR, INSIGHT_SCREENSHOT_KEY } from 'scenes/insights/insightImageCapture'
import { insightLogic } from 'scenes/insights/insightLogic'
import { interProjectCopyLogic } from 'scenes/resource-transfer/interProjectCopyLogic'
import { urls } from 'scenes/urls'

import { ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import {
    isDataTableNode,
    isDataVisualizationNode,
    isEventsQuery,
    isHogQLQuery,
    isInsightVizNode,
} from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ExporterFormat,
    InsightLogicProps,
    InsightShortId,
    QueryBasedInsightModel,
} from '~/types'

import { metricsLogic } from 'products/data_catalog/frontend/metricsLogic'
import { endpointLogic } from 'products/endpoints/frontend/endpointLogic'

import { insightModalsLogic } from '../insightModalsLogic'
import { openSaveAsCohortDialog } from './insightSidePanelDialogs'

const RESOURCE_TYPE = 'insight'

export function InsightPanelActions({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const theInsightLogic = insightLogic(insightLogicProps)
    const { insightProps, insight, hasDashboardItemId, insightDuplicating } = useValues(theInsightLogic)
    const { duplicateInsight, setInsightMetadata } = useActions(theInsightLogic)

    const theInsightDataLogic = insightDataLogic(insightProps)
    const { query, hogQL, exportContext, hogQLVariables, canEditInSqlEditor, insightDataLoading, insightDataError } =
        useValues(theInsightDataLogic)

    const { createStaticCohort } = useActions(exportsLogic)
    const { openCreateFromInsightModal } = useActions(endpointLogic)
    const { push } = useActions(router)
    const { openAddToDashboardModal, openTerraformModal } = useActions(insightModalsLogic(insightLogicProps))

    const { canCopyToProject } = useValues(interProjectCopyLogic)
    const { downloadImage } = useActions(captureImageLogic)

    const isSavedInsight = hasDashboardItemId && !!insight?.id && !!insight?.short_id

    // Creating an endpoint from an insight is a create operation, so it's gated on resource-level access.
    const createEndpointAccessReason = getAccessControlDisabledReason(
        AccessControlResourceType.Endpoint,
        AccessControlLevel.Editor
    )
    const sharingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SharingConfiguration,
        AccessControlLevel.Viewer
    )
    const canExport = exportContext != null && insight.short_id != null
    // Only an InsightViz renders the results card the browser-side capture targets. Anything else
    // still goes through the server-side PNG render.
    const canCaptureImage = isInsightVizNode(query)
    const captureTarget = {
        selector: INSIGHT_GRAPH_SELECTOR,
        screenshotKey: INSIGHT_SCREENSHOT_KEY,
        name: insight.name || insight.derived_name || undefined,
    }
    // A browser capture takes whatever is on screen. The results card renders before the chart does, so
    // capturing mid-load or after a failed query produces a valid PNG of an empty card.
    const captureDisabledReasons = {
        'Wait for the insight to finish loading': insightDataLoading,
        'The insight has no results to capture': !!insightDataError,
    }
    const showCohort =
        hogQL != null &&
        (isDataTableNode(query) || isDataVisualizationNode(query) || isHogQLQuery(query) || isEventsQuery(query))

    return (
        <ScenePanelActionsSection>
            <SceneDuplicate
                dataAttrKey={RESOURCE_TYPE}
                loading={insightDuplicating}
                onClick={() => duplicateInsight(insight as QueryBasedInsightModel, true)}
            />
            {isSavedInsight && canCopyToProject && (
                <ButtonPrimitive
                    menuItem
                    onClick={() => push(urls.resourceTransfer('Insight', insight.id!))}
                    data-attr="insight-copy-to-project"
                    tooltip="Copy this insight to another project"
                >
                    <IconCopy />
                    Copy to another project
                </ButtonPrimitive>
            )}
            {canCaptureImage && (
                <SceneCopyImageButton
                    target={captureTarget}
                    dataAttrKey={RESOURCE_TYPE}
                    disabledReasons={captureDisabledReasons}
                />
            )}
            <SceneFavorite
                dataAttrKey={RESOURCE_TYPE}
                onClick={() => setInsightMetadata({ favorited: !insight.favorited })}
                isFavorited={insight.favorited ?? false}
                disabledReasons={
                    !isSavedInsight ? { 'You must save the insight first before favoriting it': true } : undefined
                }
            />

            <SceneAddToNotebookDropdownMenu
                shortId={insight.short_id}
                dataAttrKey={RESOURCE_TYPE}
                disabledReasons={
                    !isSavedInsight
                        ? { 'You must save the insight first before adding it to a notebook': true }
                        : undefined
                }
            />

            <SceneAddToDashboardButton
                dashboard={isSavedInsight ? { onClick: openAddToDashboardModal } : undefined}
                dataAttrKey={RESOURCE_TYPE}
                disabledReasons={
                    !isSavedInsight
                        ? { 'You must save the insight first before adding it to a dashboard': true }
                        : undefined
                }
            />

            <SceneSubscribeButton
                insight={insight}
                dataAttrKey={RESOURCE_TYPE}
                disabledReasons={
                    !isSavedInsight ? { 'You must save the insight first before subscribing to it': true } : undefined
                }
            />

            <SceneAlertsButton
                insightId={insight.id!}
                insightShortId={insight.short_id as InsightShortId}
                insightLogicProps={insightLogicProps}
                dataAttrKey={RESOURCE_TYPE}
                disabledReasons={
                    !isSavedInsight ? { 'You must save the insight first before adding alerts to it': true } : undefined
                }
            />

            <SceneShareButton
                buttonProps={{
                    menuItem: true,
                    onClick: () => push(urls.insightSharing(insight.short_id!)),
                }}
                dataAttrKey={RESOURCE_TYPE}
                disabledReasons={{
                    'You must save the insight first before sharing it as a template': !isSavedInsight,
                    ...(sharingDisabledReason ? { [sharingDisabledReason]: true } : {}),
                }}
            />

            {canExport ? (
                <SceneExportDropdownMenu
                    insightShortId={insight.short_id}
                    dropdownMenuItems={[
                        {
                            format: ExporterFormat.PNG,
                            insight: insight.id,
                            context: exportContext,
                            dataAttr: `${RESOURCE_TYPE}-export-png`,
                            onClick: canCaptureImage ? () => downloadImage(captureTarget) : undefined,
                            disabledReasons: canCaptureImage ? captureDisabledReasons : undefined,
                        },
                        {
                            format: ExporterFormat.CSV,
                            context: exportContext,
                            dataAttr: `${RESOURCE_TYPE}-export-csv`,
                        },
                        {
                            format: ExporterFormat.XLSX,
                            context: exportContext,
                            dataAttr: `${RESOURCE_TYPE}-export-xlsx`,
                        },
                    ]}
                />
            ) : null}

            <ButtonPrimitive onClick={openTerraformModal} menuItem data-attr={`${RESOURCE_TYPE}-manage-terraform`}>
                <IconCode2 />
                Manage with Terraform
            </ButtonPrimitive>

            <ButtonPrimitive
                onClick={openCreateFromInsightModal}
                menuItem
                disabledReasons={{
                    'You must save the insight first before creating an endpoint from it': !isSavedInsight,
                    ...(createEndpointAccessReason ? { [createEndpointAccessReason]: true } : {}),
                }}
            >
                <IconEndpoints />
                Create endpoint
            </ButtonPrimitive>

            <CreateMetricFromInsightButton isSavedInsight={isSavedInsight} insightShortId={insight?.short_id} />

            {canEditInSqlEditor && (
                <Link
                    to={urls.sqlEditor({ query: hogQL ?? undefined })}
                    buttonProps={{
                        'data-attr': `${RESOURCE_TYPE}-edit-sql`,
                        menuItem: true,
                    }}
                >
                    <IconPencil />
                    Edit in SQL editor
                </Link>
            )}

            {showCohort && (
                <ButtonPrimitive
                    data-attr={`${RESOURCE_TYPE}-save-as-cohort`}
                    onClick={() => openSaveAsCohortDialog(createStaticCohort, hogQL!, hogQLVariables)}
                    menuItem
                >
                    <IconPeople />
                    Save as static cohort
                </ButtonPrimitive>
            )}

            {isSavedInsight && <SceneMetalyticsSummaryButton dataAttrKey={RESOURCE_TYPE} />}
        </ScenePanelActionsSection>
    )
}

function CreateMetricFromInsightButton({
    isSavedInsight,
    insightShortId,
}: {
    isSavedInsight: boolean
    insightShortId?: string
}): JSX.Element | null {
    const { openMetricFromInsightModal } = useActions(metricsLogic)
    const { allMetrics } = useValues(metricsLogic)

    // A metric already snapshots this insight, so don't offer to create a duplicate.
    if (insightShortId && allMetrics.some((metric) => metric.source_insight_short_id === insightShortId)) {
        return null
    }

    return (
        <ButtonPrimitive
            onClick={openMetricFromInsightModal}
            menuItem
            disabledReasons={{
                'You must save the insight first before creating a metric from it': !isSavedInsight,
            }}
        >
            <IconGraph />
            Create metric
        </ButtonPrimitive>
    )
}
