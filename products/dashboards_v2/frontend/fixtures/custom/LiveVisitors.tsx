import { useEffect, useState } from 'react'

import { Dot, Progress, ProgressLabel, ProgressValue, Text } from '@posthog/quill'

const TICK_MS = 2000
const DAILY_GOAL = 2000

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product renders its own custom content in a dashboard.
export function LiveVisitors(): JSX.Element {
    const [online, setOnline] = useState(42)
    const [signups, setSignups] = useState(1240)
    useEffect(() => {
        const timer = setInterval(() => {
            setOnline((count) => Math.max(5, count + Math.round(Math.random() * 8 - 4)))
            setSignups((count) => count + Math.round(Math.random() * 3))
        }, TICK_MS)
        return () => clearInterval(timer)
    }, [])
    return (
        <div className="flex h-full flex-col justify-between gap-3">
            <div className="flex items-center gap-2">
                <Dot variant="success" pulse />
                <Text size="sm" variant="muted">
                    Online now
                </Text>
            </div>
            <div className="text-3xl font-semibold tabular-nums" aria-live="polite">
                {online}
            </div>
            <Progress value={Math.min(100, (signups / DAILY_GOAL) * 100)} variant="success">
                <ProgressLabel>
                    {signups.toLocaleString()} of {DAILY_GOAL.toLocaleString()} sign-ups today
                </ProgressLabel>
                <ProgressValue />
            </Progress>
        </div>
    )
}
