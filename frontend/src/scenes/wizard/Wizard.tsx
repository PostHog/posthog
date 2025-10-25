import { useActions, useValues } from 'kea'

import { HeartHog, SurprisedHog } from 'lib/components/hedgehogs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { wizardLogic } from './wizardLogic'

export const scene: SceneExport = {
    component: Wizard,
    logic: wizardLogic,
}

export function Wizard(): JSX.Element {
    const { view, selectedProjectId, availableProjects } = useValues(wizardLogic)
    const { setSelectedProjectId, continueToAuthentication } = useActions(wizardLogic)

    return (
        <div className="flex h-full w-full items-center justify-center">
            <div className="px-12 py-8 text-center flex flex-col items-center max-w-160 w-full">
                {view === 'project' && (
                    <div className="max-w-xs">
                        <div className="mb-8">
                            <h1 className="text-3xl font-bold mb-3">AI wizard</h1>
                            <p className="text-muted-alt">
                                Select which project the wizard should use to install PostHog.
                            </p>
                        </div>

                        <div className="space-y-6">
                            <div className="justify-start items-start flex flex-col">
                                <label className="align-start block text-sm font-medium mb-3">Project</label>
                                <LemonSelect
                                    value={selectedProjectId ?? undefined}
                                    onChange={(projectId: number) => setSelectedProjectId(projectId)}
                                    options={availableProjects}
                                    placeholder="Choose a project..."
                                    className="w-full"
                                />
                            </div>

                            <div className="pt-4 flex items-center justify-center">
                                <LemonButton
                                    type="primary"
                                    onClick={continueToAuthentication}
                                    disabledReason={
                                        !selectedProjectId ? 'Please select a project to continue.' : undefined
                                    }
                                    className="w-auto"
                                >
                                    Continue setup
                                </LemonButton>
                            </div>
                        </div>
                    </div>
                )}
                {view === 'pending' && (
                    <>
                        <h1 className="text-lg font-bold">Authenticating setup wizard...</h1>
                        <Spinner className="w-16 h-16 mt-12" />
                    </>
                )}
                {view === 'success' && (
                    <>
                        <h1 className="text-3xl font-bold">Success!</h1>
                        <div className="max-w-60 mb-12">
                            <HeartHog className="w-48 h-48" />
                        </div>
                        <p className="text-lg">You're all set! You can return to the PostHog setup wizard.</p>
                    </>
                )}
                {view === 'invalid' && (
                    <>
                        <h1 className="text-xl font-bold">Something went wrong!</h1>
                        <SurprisedHog className="h-48 w-48" />
                        <p className="text-lg">
                            There was a problem authenticating the setup wizard. Please try again later.
                        </p>
                    </>
                )}
            </div>
        </div>
    )
}
