import { useActions, useValues } from 'kea'

import { IconCheck, IconCode, IconDatabase, IconEllipsis, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonMenu, Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { HealthIssueList } from './components/HealthIssueList'
import { HealthIssueSummaryCards } from './components/HealthIssueSummaryCards'
import { healthSceneLogic } from './healthSceneLogic'

const HealthCard = ({
    title,
    description,
    icon,
    to,
}: {
    title: string
    description: string
    icon: React.ReactNode
    to: string
}): JSX.Element => {
    return (
        <Link
            to={to}
            className="flex flex-col gap-4 justify-between border border-primary bg-surface-primary rounded p-8 transition-colors cursor-pointer h-full shadow hover:border-accent"
        >
            <div className="size-8 flex items-center justify-center text-primary">{icon}</div>
            <div>
                <h3 className="text-sm font-semibold line-clamp-2 flex-1 mb-0">{title}</h3>
                <p className="text-sm text-text-tertiary mb-0">{description}</p>
            </div>
        </Link>
    )
}

const DetailedViewCards = (): JSX.Element => {
    return (
        <div className="grid grid-cols-1 @2xl/main-content:grid-cols-3 gap-4 max-w-3xl">
            <HealthCard
                title="Ingestion warnings"
                description="Click to view"
                icon={<IconWarning className="size-6" />}
                to={urls.ingestionWarnings()}
            />
            <HealthCard
                title="SDK health"
                description="Click to view"
                icon={<IconCode className="size-6" />}
                to={urls.sdkDoctor()}
            />
            <HealthCard
                title="Pipelines status"
                description="Click to view"
                icon={<IconDatabase className="size-6" />}
                to={urls.pipelineStatus()}
            />
        </div>
    )
}

const LegacyHealthScene = (): JSX.Element => {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Health"
                description="See an at-a-glance view of the health of your project."
                resourceType={{ type: 'health' }}
            />
            <DetailedViewCards />
        </SceneContent>
    )
}

const UnifiedHealthScene = (): JSX.Element => {
    const { showDismissed, healthIssuesLoading } = useValues(healthSceneLogic)
    const { refreshHealthData, setShowDismissed } = useActions(healthSceneLogic)

    return (
        <SceneContent>
            <SceneTitleSection name="Health" description={null} resourceType={{ type: 'health' }} />

            <div className="flex items-center justify-between -mt-2 mb-2">
                <p className="text-sm mb-0">See an at-a-glance view of the health of your project.</p>
                <div className="flex items-center gap-1">
                    <LemonButton
                        icon={<IconRefresh />}
                        type="tertiary"
                        size="small"
                        tooltip="Refresh"
                        loading={healthIssuesLoading}
                        onClick={() => refreshHealthData()}
                    />
                    <LemonMenu
                        items={[
                            {
                                label: 'Show dismissed',
                                icon: showDismissed ? <IconCheck /> : undefined,
                                onClick: () => setShowDismissed(!showDismissed),
                            },
                        ]}
                        placement="bottom-end"
                    >
                        <LemonButton icon={<IconEllipsis />} type="tertiary" size="small" />
                    </LemonMenu>
                </div>
            </div>

            <div className="flex flex-col gap-6 max-w-5xl">
                <HealthIssueSummaryCards />
                <HealthIssueList />
            </div>
        </SceneContent>
    )
}

export const HealthScene = (): JSX.Element => {
    const { unifiedHealthPageEnabled } = useValues(healthSceneLogic)
    return unifiedHealthPageEnabled ? <UnifiedHealthScene /> : <LegacyHealthScene />
}

export const scene: SceneExport = {
    component: HealthScene,
    logic: healthSceneLogic,
}
