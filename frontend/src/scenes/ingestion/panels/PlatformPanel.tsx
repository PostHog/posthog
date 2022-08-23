import React from 'react'
import { useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { THIRD_PARTY, BOOKMARKLET, platforms } from 'scenes/ingestion/constants'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { LemonDivider } from 'lib/components/LemonDivider'

export function PlatformPanel(): JSX.Element {
    const { setPlatform } = useActions(ingestionLogic)

    return (
        // We want a forced width for this view only
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ maxWidth: 400 }}>
            <h1 className="ingestion-title">Welcome to PostHog</h1>
            <p>
                First things first, where do you want to send events from? You can always instrument more sources later.
            </p>
            <LemonDivider thick dashed className="my-6" />
            <div className="flex flex-col mb-6">
                {platforms.map((platform) => (
                    <LemonButton
                        key={platform}
                        fullWidth
                        center
                        size="large"
                        type="primary"
                        className="mb-2"
                        onClick={() => setPlatform(platform)}
                    >
                        {platform}
                    </LemonButton>
                ))}
                <LemonButton
                    onClick={() => setPlatform(THIRD_PARTY)}
                    fullWidth
                    center
                    size="large"
                    className="mb-2"
                    type="primary"
                >
                    {THIRD_PARTY}
                </LemonButton>
                <LemonButton type="secondary" size="large" fullWidth center onClick={() => setPlatform(BOOKMARKLET)}>
                    {BOOKMARKLET}
                </LemonButton>
            </div>
        </div>
    )
}
