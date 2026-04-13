import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { DashboardsTab } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { dashboardTemplateCopyLogic, type DashboardTemplateCopyLogicProps } from './dashboardTemplateCopyLogic'

/** Aligns with `urls.dashboardTemplateCopyToProject` query shape (`source_team`). */
function sourceTeamQueryFromSearchParams(searchParams: Record<string, any>): {
    sourceTeamId: number | undefined
    hasValidSourceTeamQuery: boolean
} {
    const raw = searchParams.source_team
    const s = raw === undefined || raw === null ? '' : typeof raw === 'number' ? String(raw) : String(raw).trim()
    const hasValidSourceTeamQuery = /^\d+$/.test(s)
    return {
        sourceTeamId: hasValidSourceTeamQuery ? Number(s) : undefined,
        hasValidSourceTeamQuery,
    }
}

export const scene: SceneExport<DashboardTemplateCopyLogicProps> = {
    component: DashboardTemplateCopyScene,
    logic: dashboardTemplateCopyLogic,
    paramsToProps: ({ params: { sourceTemplateId }, searchParams }) => {
        const { sourceTeamId } = sourceTeamQueryFromSearchParams(searchParams)
        return { sourceTemplateId, sourceTeamId }
    },
}

export function DashboardTemplateCopyScene(props: DashboardTemplateCopyLogicProps): JSX.Element {
    const { searchParams } = useValues(router)
    const { hasValidSourceTeamQuery } = sourceTeamQueryFromSearchParams(searchParams)
    const logic = dashboardTemplateCopyLogic(props)
    const {
        sourceTemplate,
        sourceTemplateLoading,
        sourceTemplateLoadFailed,
        teamOptions,
        destinationTeamId,
        copyResultLoading,
    } = useValues(logic)
    const { setDestinationTeamId, submitCopy } = useActions(logic)

    const title = sourceTemplate?.template_name
        ? `Copy "${sourceTemplate.template_name}" to another project`
        : 'Copy template to another project'

    const templatesListUrl = combineUrl(urls.dashboards(), { tab: DashboardsTab.Templates }).url
    const loadFailed = sourceTemplateLoadFailed
    const hasDestinationProjects = teamOptions.length > 0
    const showNoDestinationsEmptyState = !sourceTemplateLoading && !loadFailed && !hasDestinationProjects

    return (
        <SceneContent>
            <SceneTitleSection
                name={title}
                resourceType={{ type: 'Resource Transfer' }}
                forceBackTo={{
                    name: 'Templates',
                    path: templatesListUrl,
                    key: 'dashboard-template-copy-back',
                }}
            />
            <div className="max-w-160 mt-4 mb-16 space-y-6">
                {hasValidSourceTeamQuery === false ? (
                    <LemonBanner type="info">
                        This link did not include a valid source project. We are using the project you are currently in
                        to load the template. Use &quot;Copy to another project&quot; from the templates list for a
                        complete link, or stay here if this project owns the template.
                    </LemonBanner>
                ) : null}
                {loadFailed ? (
                    <LemonBanner type="error">
                        We could not load this template. It may have been deleted, or you may need to open this page
                        from the project that owns the template.{' '}
                        <Link to={templatesListUrl} className="font-semibold">
                            Back to templates
                        </Link>
                    </LemonBanner>
                ) : null}
                <div className="space-y-2">
                    {sourceTemplateLoading ? (
                        <>
                            <p>Choose which project to copy this template to. The original will not be modified.</p>
                            <LemonSkeleton className="h-10 w-full" />
                        </>
                    ) : loadFailed ? null : showNoDestinationsEmptyState ? (
                        <div className="w-full rounded-lg border-2 border-dotted border-primary p-6">
                            <EmptyMessage
                                title="No other projects to copy to"
                                description="Create another project in this organization first. The template you are copying will not be changed."
                                buttonText="Create a project"
                                buttonTo={urls.projectCreateFirst()}
                                buttonDataAttr="dashboard-template-copy-empty-create-project"
                            />
                        </div>
                    ) : (
                        <>
                            <p>Choose which project to copy this template to. The original will not be modified.</p>
                            <div>
                                <label className="font-semibold leading-6 block mb-1">Destination project</label>
                                <LemonSelect
                                    fullWidth
                                    placeholder="Select a project"
                                    value={destinationTeamId}
                                    onChange={(value) => setDestinationTeamId(value)}
                                    options={teamOptions}
                                />
                            </div>
                        </>
                    )}
                </div>

                {destinationTeamId != null && hasDestinationProjects && !loadFailed ? (
                    <div className="flex justify-end">
                        <LemonButton type="primary" onClick={() => submitCopy()} loading={copyResultLoading}>
                            Copy
                        </LemonButton>
                    </div>
                ) : null}
            </div>
        </SceneContent>
    )
}
