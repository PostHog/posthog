import { useValues } from 'kea'
import { HeartHog, SurprisedHog } from 'lib/components/hedgehogs'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { wizardLogic } from './wizardLogic'

export const scene: SceneExport = {
    component: Wizard,
    logic: wizardLogic,
}

export function Wizard(): JSX.Element {
    const { view } = useValues(wizardLogic)

    return (
        <div className="flex h-full w-full items-center justify-center">
            <div className="px-12 py-8 text-center flex flex-col items-center max-w-160 w-full">
                {(view === 'pending' || view === 'creating') && (
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
