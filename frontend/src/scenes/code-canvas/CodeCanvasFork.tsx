import { useActions, useValues } from 'kea'

import { IconLaptop } from '@posthog/icons'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { codeCanvasForkLogic } from './codeCanvasForkLogic'

export interface CodeCanvasForkProps {
    shareToken: string
}

export const scene: SceneExport<CodeCanvasForkProps> = {
    component: CodeCanvasFork,
    logic: codeCanvasForkLogic,
    paramsToProps: ({ params: { shareToken } }) => ({
        shareToken: shareToken ?? '',
    }),
}

/**
 * Signed-in landing for a public canvas page's "open a copy" button. Copies the shared canvas
 * into the viewer's own project and forwards to the desktop bridge for the copy.
 */
export function CodeCanvasFork({ shareToken }: CodeCanvasForkProps): JSX.Element {
    const logic = codeCanvasForkLogic({ shareToken })
    const { copyLoading, error, copy } = useValues(logic)
    const { forkCanvas } = useActions(logic)

    return (
        <BridgePage view="code-canvas-fork">
            <div className="flex flex-col items-center gap-4 text-center max-w-lg mx-auto">
                <IconLaptop className="text-5xl shrink-0" />
                {error ? (
                    <>
                        <h2 className="text-xl font-semibold m-0">Couldn't copy this canvas</h2>
                        <p className="text-muted mb-0">{error}</p>
                        <LemonButton type="primary" onClick={forkCanvas} loading={copyLoading} disabled={copyLoading}>
                            Try again
                        </LemonButton>
                    </>
                ) : (
                    <>
                        <h2 className="text-xl font-semibold m-0">
                            {copy ? 'Opening your copy in PostHog Desktop…' : 'Copying this canvas to your project…'}
                        </h2>
                        <p className="text-muted mb-0">
                            The copy lands in your personal space. Edits there never change the original.
                        </p>
                        {!copy && <Spinner className="text-2xl" />}
                    </>
                )}
            </div>
        </BridgePage>
    )
}

export default CodeCanvasFork
