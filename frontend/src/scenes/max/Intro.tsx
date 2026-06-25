import { useValues } from 'kea'

import { JumpingLogomark } from 'lib/brand/JumpingLogomark'

import { AILiabilityNotice } from './components/AILiabilityNotice'
import { MaxChangelog } from './components/MaxChangelog'
import { maxLogic } from './maxLogic'

export function Intro({
    forceHeadline,
    forceSubheadline,
}: {
    forceHeadline?: string
    forceSubheadline?: string | null
}): JSX.Element {
    const { headline } = useValues(maxLogic)
    const headlineToUse = forceHeadline || headline
    const subheadlineToUse = forceSubheadline === null ? null : forceSubheadline || 'Build something people want.'

    return (
        <>
            <JumpingLogomark className="flex *:h-full *:w-12 p-2" />
            <div className="text-center mb-1">
                <h2 className="text-xl @2xl/main-content:text-2xl font-bold mb-2 text-balance">{headlineToUse}</h2>
                {subheadlineToUse && (
                    <div className="text-sm italic text-tertiary text-pretty py-0.5">{subheadlineToUse}</div>
                )}
            </div>
            <AILiabilityNotice />
            <MaxChangelog />
        </>
    )
}
