import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { Logomark } from 'lib/brand/Logomark'

import { MaxChangelog } from './components/MaxChangelog'
import { maxLogic } from './maxLogic'

const LOGOMARK_AIRTIME_MS = 400 // Sync with --logomark-airtime in base.scss
const CHRISTMAS_MESSAGE_DEADLINE = new Date(2025, 11, 26, 23, 59, 59, 999).getTime()
const CHRISTMAS_MESSAGES = [
    "Ho-ho-ho, let's ship something merry.",
    'All I want for Christmas is a new feature.',
    'Deck the halls with deploys and feature flags.',
    'Jingle all the way to production.',
    'Build something sleigh-worthy.',
    'Santa is watching your pull requests.',
    'Make it snow: ship it.',
    'Wrap up that roadmap with a bow.',
    'Yule love this build.',
    'Have a holly, jolly deploy.',
]

export function Intro(): JSX.Element {
    const { headline } = useValues(maxLogic)
    const [hedgehogLastJumped, setHedgehogLastJumped] = useState<number | null>(Date.now())
    const [hedgehogJumpIteration, setHedgehogJumpIteration] = useState(0)
    const isHolidayMessageActive = Date.now() <= CHRISTMAS_MESSAGE_DEADLINE
    const holidayMessage = useMemo(() => {
        if (!isHolidayMessageActive) {
            return null
        }
        const messageIndex = Math.floor(Math.random() * CHRISTMAS_MESSAGES.length)
        return CHRISTMAS_MESSAGES[messageIndex]
    }, [isHolidayMessageActive])

    const handleLogomarkClick = (): void => {
        const now = Date.now()
        if (hedgehogLastJumped && now - hedgehogLastJumped < LOGOMARK_AIRTIME_MS) {
            return // Disallows interrupting the jump animation!
        }
        setHedgehogJumpIteration(hedgehogJumpIteration + 1)
        setHedgehogLastJumped(null)
        requestAnimationFrame(() => setHedgehogLastJumped(now))
    }

    return (
        <>
            <div
                className={`flex *:h-full *:w-12 p-2 cursor-pointer ${hedgehogLastJumped ? 'animate-logomark-jump' : ''}`}
                // eslint-disable-next-line react/forbid-dom-props
                style={
                    {
                        '--logomark-jump-magnitude': hedgehogJumpIteration
                            ? 1.5 ** ((hedgehogJumpIteration % 8) - 2)
                            : 1,
                    } as React.CSSProperties
                }
                onClick={handleLogomarkClick}
            >
                <Logomark />
            </div>
            <div className="text-center mb-1">
                <h2 className="text-xl @2xl/main-content:text-2xl font-bold mb-2 text-balance">{headline}</h2>
                <div className="text-sm italic text-tertiary text-pretty py-0.5">
                    {holidayMessage ?? 'Build something people want.'}
                </div>
            </div>
            <MaxChangelog />
        </>
    )
}
