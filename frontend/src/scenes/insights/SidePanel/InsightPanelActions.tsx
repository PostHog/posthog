import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCode2, IconEndpoints, IconPencil, IconPeople } from '@posthog/icons'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'
import { SceneAddToDashboardButton } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToDashboardButton'
import { SceneAddToNotebookDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneAddToNotebookDropdownMenu'
import { SceneExportDropdownMenu } from 'lib/components/Scenes/InsightOrDashboard/SceneExportDropdownMenu'
import { SceneAlertsButton } from 'lib/components/Scenes/SceneAlertsButton'
import { SceneDuplicate } from 'lib/components/Scenes/SceneDuplicate'
import { SceneFavorite } from 'lib/components/Scenes/SceneFavorite'
import { SceneMetalyticsSummaryButton } from 'lib/components/Scenes/SceneMetalyticsSummaryButton'
import { SceneShareButton } from 'lib/components/Scenes/SceneShareButton'
import { SceneSubscribeButton } from 'lib/components/Scenes/SceneSubscribeButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { urls } from 'scenes/urls'

import { ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { isDataTableNode, isDataVisualizationNode, isEventsQuery, isHogQLQuery } from '~/queries/utils'
import { ExporterFormat, InsightLogicProps, InsightShortId, QueryBasedInsightModel } from '~/types'

import { endpointLogic } from 'products/endpoints/frontend/endpointLogic'

import { insightModalsLogic } from '../insightModalsLogic'
import { openSaveAsCohortDialog } from './insightSidePanelDialogs'

const RESOURCE_TYPE = 'insight'

export function InsightPanelActions({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const theInsightLogic = insightLogic(insightLogicProps)
    const { insightProps, insight, hasDashboardItemId } = useValues(theInsightLogic)
    const { duplicateInsight, setInsightMetadata } = useActions(theInsightLogic)

    const theInsightDataLogic = insightDataLogic(insightProps)
    const { query, hogQL, exportContext, hogQLVariables } = useValues(theInsightDataLogic)

    const { createStaticCohort } = useActions(exportsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openCreateFromInsightModal } = useActions(endpointLogic({ tabId: insightProps.tabId || '' }))
    const { push } = useActions(router)
    const { openAddToDashboardModal, openTerraformModal } = useActions(insightModalsLogic(insightLogicProps))

    const isSavedInsight = hasDashboardItemId && !!insight?.id && !!insight?.short_id
    const canExport = exportContext != null && insight.short_id != null
    const canEditInSqlEditor =
        hogQL != null && !isHogQLQuery(query) && !(isDataVisualizationNode(query) && isHogQLQuery(query.source))
    const showCohort =
        hogQL != null &&
        (isDataTableNode(query) || isDataVisualizationNode(query) || isHogQLQuery(query) || isEventsQuery(query))

    return (
        <ScenePanelActionsSection>
            <SceneDuplicate
                dataAttrKey={RESOURCE_TYPE}
                onClick={() => duplicateInsight(insight as QueryBasedInsightModel, true)}
            />
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
                disabledReasons={
                    !isSavedInsight
                        ? { 'You must save the insight first before sharing it as a template': true }
                        : undefined
                }
            />

            {canExport ? (
                <SceneExportDropdownMenu
                    dropdownMenuItems={[
                        {
                            format: ExporterFormat.PNG,
                            insight: insight.id,
                            context: exportContext,
                            dataAttr: `${RESOURCE_TYPE}-export-png`,
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

            {featureFlags[FEATURE_FLAGS.ENDPOINTS] ? (
                <ButtonPrimitive
                    onClick={openCreateFromInsightModal}
                    menuItem
                    disabledReasons={
                        !isSavedInsight
                            ? { 'You must save the insight first before creating an endpoint from it': true }
                            : undefined
                    }
                >
                    <IconEndpoints />
                    Create endpoint
                </ButtonPrimitive>
            ) : null}

            {canEditInSqlEditor && (
                <Link
                    to={urls.sqlEditor({ query: hogQL })}
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
