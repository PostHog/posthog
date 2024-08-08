import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { HedgehogBuddyStatic } from 'lib/components/HedgehogBuddy/HedgehogBuddyRender'
import { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { maxLogic } from './maxLogic'

export const scene: SceneExport = {
    component: Max,
    logic: maxLogic,
}

export function Max(): JSX.Element {
    const { user } = useValues(userLogic)
    const { thread } = useValues(maxLogic)
    const { askMax } = useActions(maxLogic)

    const [question, setQuestion] = useState('')

    return (
        <>
            <div className="flex flex-col gap-4 grow ">
                {thread.map((item, index) => (
                    <div key={index} className="bg-accent-3000 border p-2 rounded">
                        {JSON.stringify(item)}
                    </div>
                ))}
            </div>
            <div className="relative flex items-start mb-4">
                <div className="flex -ml-2.5 -mt-2">
                    <HedgehogBuddyStatic
                        accessories={user?.hedgehog_config?.accessories}
                        color={user?.hedgehog_config?.color}
                        size={80}
                        waveOnAppearance
                    />
                </div>
                <LemonInput
                    value={question}
                    onChange={(value) => setQuestion(value)}
                    placeholder="Hey, I'm Max! What would you like to know about your product?"
                    fullWidth
                    size="large"
                    autoFocus
                    suffix={
                        <LemonButton type="primary" onClick={() => askMax(question)}>
                            Ask Max
                        </LemonButton>
                    }
                />
            </div>
        </>
    )
}
