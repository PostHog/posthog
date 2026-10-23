import { useActions, useValues } from 'kea'
import { type ReactNode } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { SceneExport } from 'scenes/sceneTypes'

import { cliLiveLogic } from './cliLiveLogic'

export const scene: SceneExport = {
    component: CLILive,
    logic: cliLiveLogic,
}

function CLILiveCard({ title, sub, children }: { title: string; sub?: string; children?: ReactNode }): JSX.Element {
    return (
        <AuthScene notes={['// posthog live', '// events, in your terminal']}>
            <AuthSceneCard>
                <AuthCardTitle title={title} sub={sub} />
                {children}
            </AuthSceneCard>
        </AuthScene>
    )
}

export function CLILive(): JSX.Element {
    const { port, projects, projectsLoading, error, redirected, selectedProjectId } = useValues(cliLiveLogic)
    const { selectProject } = useActions(cliLiveLogic)

    if (!port) {
        return (
            <CLILiveCard title="Missing port parameter">
                <AuthBanner variant="danger">
                    This page should be opened from the PostHog Live TUI. Please run <code>posthog-live</code> in your
                    terminal.
                </AuthBanner>
            </CLILiveCard>
        )
    }

    if (redirected) {
        return (
            <CLILiveCard title="Authorization complete">
                <AuthBanner variant="success">You can close this tab and return to your terminal.</AuthBanner>
            </CLILiveCard>
        )
    }

    if (error) {
        return (
            <CLILiveCard title="Authorization failed">
                <AuthBanner variant="danger">{error}</AuthBanner>
            </CLILiveCard>
        )
    }

    if (projectsLoading || projects.length === 1) {
        return (
            <CLILiveCard title="Authorizing PostHog Live…">
                <div className="flex justify-center">
                    <Spinner className="text-2xl" />
                </div>
            </CLILiveCard>
        )
    }

    return (
        <CLILiveCard title="Select a project" sub="Pick the project to stream live events from.">
            <LemonSelect
                data-attr="cli-live-project-select"
                placeholder="Select a project"
                value={selectedProjectId}
                onChange={(value) => {
                    if (value) {
                        selectProject(value)
                    }
                }}
                options={projects.map((project) => ({
                    label: project.name,
                    value: project.id,
                }))}
                fullWidth
            />
        </CLILiveCard>
    )
}
