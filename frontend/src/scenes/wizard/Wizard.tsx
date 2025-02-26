import { useValues } from 'kea'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { HeartHog, ProfessorHog, SurprisedHog } from 'lib/components/hedgehogs'
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
        <BridgePage view="wizard" fixedWidth={false}>
            <div className="px-12 py-8 text-center flex flex-col items-center max-w-160 w-full">
                {view === 'pending' ||
                    (view === 'creating' && (
                        <>
                            <h1 className="text-xl font-bold">Generating your API token...</h1>
                            <div className="max-w-60 my-10">
                                <ProfessorHog className="w-full h-full" />
                            </div>
                            <Spinner className="text-xl mb-12" />
                        </>
                    ))}
                {view === 'success' && (
                    <>
                        <h1 className="text-3xl font-bold">Success!</h1>
                        <div className="max-w-60 mb-12">
                            <HeartHog className="w-full h-full" />
                        </div>
                        <p>Your API token has been generated. You can now use it in your PostHog dashboard.</p>
                    </>
                )}
                {view === 'invalid' && (
                    <>
                        <h1 className="text-xl font-bold">Something went wrong!</h1>
                        <SurprisedHog className="h-48 w-48" />
                        <p className="text-lg">There was a problem authenticating your wizard. Please try again.</p>
                    </>
                )}
            </div>
        </BridgePage>
    )
}
