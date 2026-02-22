import { Link } from '@posthog/lemon-ui'
import React from 'react'

export const SessionReplayFinalSteps = (): React.ReactElement => {
    return (
        <>
            <p>
                Visit your site or app and interact with it for at least 10 seconds to generate a recording. Navigate
                between pages, click buttons, and fill out forms to capture meaningful interactions.
            </p>
            <p>
                <Link target="/replay/home">Watch your first recording →</Link>
            </p>
        </>
    )
}
