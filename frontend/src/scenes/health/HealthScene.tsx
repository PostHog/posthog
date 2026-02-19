import { IconCode, IconDatabase, IconWarning } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { healthSceneLogic } from './healthSceneLogic'

export const scene: SceneExport = {
    component: HealthScene,
    logic: healthSceneLogic,
}

function HealthCard({
    title,
    description,
    icon,
    to,
}: {
    title: string
    description: string
    icon: React.ReactNode
    to: string
}): JSX.Element {
    return (
        // Copying survey template here
        // TODO: move to components folder and update survey template to use it
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

export function HealthScene(): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Health"
                description="See an at-a-glance view of the health of your project."
                resourceType={{
                    type: 'health',
                }}
            />

            <div className="grid grid-cols-1 @2xl/main-content:grid-cols-3 gap-4 max-w-3xl">
                {/* TODO: move ingestions warnings to under /health route? */}
                {/* TODO: pass in actual statuses and change icon to reflect status */}
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
        </SceneContent>
    )
}
