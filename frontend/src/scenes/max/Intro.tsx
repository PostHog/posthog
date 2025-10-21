import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { userLogic } from 'scenes/userLogic'

import { Logomark } from '~/toolbar/assets/Logomark'

import { maxLogic } from './maxLogic'

export function Intro(): JSX.Element {
    const { headline } = useValues(maxLogic)
    const { user } = useValues(userLogic)

    const shouldShowMaxRebrandMessage: boolean = !!user && dayjs(user.date_joined).isBefore('2025-10-21')

    return (
        <>
            <div className="flex *:h-full *:w-12 animate-logomark-jump">
                <Logomark />
            </div>
            <div className="text-center mb-1">
                <h2 className="text-xl @md/max-welcome:text-2xl font-bold my-2 text-balance">{headline}</h2>
                <div className="text-sm italic text-tertiary text-pretty py-0.5">
                    {shouldShowMaxRebrandMessage
                        ? 'Max AI is now PostHog AI – a core part of PostHog.'
                        : 'Build something people want.'}
                </div>
            </div>
        </>
    )
}
