import { offset } from '@floating-ui/react'
import { useValues } from 'kea'
import { hedgehogModeLogic } from 'lib/components/HedgehogMode/hedgehogModeLogic'
import { HedgehogModeStatic } from 'lib/components/HedgehogMode/HedgehogModeRender'
import { uuid } from 'lib/utils'
import { useMemo, useState } from 'react'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { maxLogic } from './maxLogic'

const HEADLINES = [
    'How can I help you build?',
    'What are you curious about?',
    'How can I help you understand users?',
    'What do you want to know today?',
]

export function Intro(): JSX.Element {
    const { hedgehogConfig } = useValues(hedgehogModeLogic)
    const { conversation } = useValues(maxLogic)

    const [hedgehogDirection, setHedgehogDirection] = useState<'left' | 'right'>('right')

    const headline = useMemo(() => {
        if (process.env.STORYBOOK) {
            return HEADLINES[0] // Preventing UI snapshots from being different every time
        }
        return HEADLINES[parseInt((conversation?.id || uuid()).split('-').at(-1) as string, 16) % HEADLINES.length]
    }, [conversation?.id])

    return (
        <>
            <div className="flex">
                <AIConsentPopoverWrapper
                    placement={`${hedgehogDirection}-end`}
                    fallbackPlacements={[`${hedgehogDirection === 'right' ? 'left' : 'right'}-end`]}
                    middleware={[offset(-12)]}
                    showArrow
                >
                    <HedgehogModeStatic {...hedgehogConfig} size={100} />
                </AIConsentPopoverWrapper>
            </div>
            <div className="mb-1 text-center">
                <h2 className="text-xl @md/max-welcome:text-2xl font-bold mb-2 text-balance">{headline}</h2>
                <div className="text-sm text-secondary text-balance">
                    I'm Max, here to help you build a successful&nbsp;product. Ask&nbsp;me about your product and
                    your&nbsp;users.
                </div>
            </div>
        </>
    )
}
