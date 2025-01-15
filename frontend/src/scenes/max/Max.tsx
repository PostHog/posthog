import { BindLogic, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { Intro } from './Intro'
import { maxLogic } from './maxLogic'
import { QuestionInput } from './QuestionInput'
import { QuestionSuggestions } from './QuestionSuggestions'
import { Thread } from './Thread'

export const scene: SceneExport = {
    component: Max,
}

export function Max(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG]) {
        return <NotFound object="page" caption="You don't have access to AI features yet." />
    }

    return (
        <BindLogic logic={maxLogic} props={{ conversationId: null }}>
            <MaxInstance />
        </BindLogic>
    )
}

export function MaxInstance(): JSX.Element {
    const { threadGrouped } = useValues(maxLogic)

    return (
        <>
            {!threadGrouped.length ? (
                <div className="relative flex flex-col gap-3 px-4 pb-8 items-center grow justify-center">
                    <Intro />
                    <QuestionInput />
                    <QuestionSuggestions />
                </div>
            ) : (
                <>
                    <Thread />
                    <QuestionInput />
                </>
            )}
        </>
    )
}
