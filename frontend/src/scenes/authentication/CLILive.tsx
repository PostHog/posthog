import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { cliLiveLogic } from './cliLiveLogic'

export const scene: SceneExport = {
    component: CLILive,
    logic: cliLiveLogic,
}

export function CLILive(): JSX.Element {
    const { port, projects, projectsLoading, error, redirected, selectedProjectId } = useValues(cliLiveLogic)
    const { selectProject } = useActions(cliLiveLogic)

    if (!port) {
        return (
            <BridgePage view="login" hedgehog>
                <div className="text-center space-y-4">
                    <h2>Missing port parameter</h2>
                    <LemonBanner type="error">
                        This page should be opened from the PostHog Live TUI. Please run <code>posthog-live</code> in
                        your terminal.
                    </LemonBanner>
                </div>
            </BridgePage>
        )
    }

    if (redirected) {
        return (
            <BridgePage view="login" hedgehog={false}>
                <div className="text-center space-y-4">
                    <h2>Authorization complete</h2>
                    <LemonBanner type="success">
                        <div className="space-y-2">
                            <p className="font-semibold">You can close this tab and return to your terminal.</p>
                        </div>
                    </LemonBanner>
                </div>
            </BridgePage>
        )
    }

    if (error) {
        return (
            <BridgePage view="login" hedgehog>
                <div className="text-center space-y-4">
                    <h2>Authorization failed</h2>
                    <LemonBanner type="error">{error}</LemonBanner>
                </div>
            </BridgePage>
        )
    }

    if (projectsLoading || projects.length === 1) {
        return (
            <BridgePage view="login" hedgehog>
                <div className="text-center space-y-4">
                    <h2>Authorizing PostHog Live...</h2>
                    <SpinnerOverlay />
                </div>
            </BridgePage>
        )
    }

    return (
        <BridgePage
            view="login"
            hedgehog
            message={
                <>
                    Authorize
                    <br />
                    PostHog Live
                </>
            }
        >
            <div className="space-y-4">
                <h2>Select a project</h2>
                <p className="text-muted text-sm">Choose which project to stream live events from.</p>
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
            </div>
        </BridgePage>
    )
}
