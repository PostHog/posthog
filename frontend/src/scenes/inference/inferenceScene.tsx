import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { inferenceLogic } from 'scenes/inference/inferenceLogic'
import { SceneExport } from 'scenes/sceneTypes'

export function InferenceScene(): JSX.Element {
    const { inputText, submitInputTextLoading, threadRaw } = useValues(inferenceLogic)
    const { setInputText, submit } = useActions(inferenceLogic)

    return (
        <>
            <PageHeader />
            <LemonBanner type="warning" className="my-4">
                <p className="flex-1 min-w-full sm:min-w-0">
                    LLM Inference is in Alpha, and not yet available for general use. It may be turned off at any time.
                </p>
            </LemonBanner>
            {/* Add some UI to send a sample input*/}
            <code>{JSON.stringify(threadRaw, null, 2)}</code>
            <LemonInput
                placeholder="Try it"
                value={inputText}
                onChange={setInputText}
                className="w-full"
                disabled={submitInputTextLoading}
            />
            <LemonButton onClick={submit} loading={submitInputTextLoading}>
                Send
            </LemonButton>
        </>
    )
}

export const scene: SceneExport = {
    component: InferenceScene,
    logic: inferenceLogic,
}
