import './Max.scss'

import { BindLogic, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils'
import React, { useMemo } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { Intro } from './Intro'
import { maxLogic } from './maxLogic'
import { QuestionInput } from './QuestionInput'
import { QuestionSuggestions } from './QuestionSuggestions'
import { Thread } from './Thread'

export const scene: SceneExport = {
    component: Max,
    logic: maxLogic,
}

export function Max(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const sessionId = useMemo(() => uuid(), [])

    if (!featureFlags[FEATURE_FLAGS.ARTIFICIAL_HOG]) {
        return <NotFound object="page" caption="You don't have access to AI features yet." />
    }

    return (
        <BindLogic logic={maxLogic} props={{ sessionId }}>
            <MaxInstance />
        </BindLogic>
    )
}

function MaxInstance(): JSX.Element {
    const { thread } = useValues(maxLogic)

    return (
        <>
            {!thread.length ? (
                <div className="relative flex flex-col gap-4 px-4 items-center grow justify-center">
                    <Intro />
                    <div className="flex flex-col gap-3 items-center w-[min(40rem,100%)]">
                        <QuestionInput />
                        <QuestionSuggestions />
                    </div>
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
