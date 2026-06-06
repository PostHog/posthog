import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { shareNudgeLogic } from './shareNudgeLogic'
import { ShareNudgePrompt } from './ShareNudgePrompt'

const meta: Meta = {
    title: 'Scenes-App/Web Analytics/Share nudge prompt',
    parameters: {
        testOptions: {
            waitForSelector: '[data-attr=web-analytics-share-nudge-prompt]',
        },
    },
}
export default meta

export function IntentPrompt(): JSX.Element {
    const { showPrompt } = useActions(shareNudgeLogic)

    useEffect(() => {
        showPrompt({ x: 24, y: 24 })
    }, [showPrompt])

    return (
        <div className="relative h-60 w-full">
            <ShareNudgePrompt />
        </div>
    )
}
