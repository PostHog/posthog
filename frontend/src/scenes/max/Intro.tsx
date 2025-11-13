import { useValues } from 'kea'

import { Link, Tooltip } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand/Logomark'
import { dayjs } from 'lib/dayjs'
import { userLogic } from 'scenes/userLogic'

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
                    {shouldShowMaxRebrandMessage ? (
                        <Tooltip
                            title={
                                <>
                                    As consolation, you can still{' '}
                                    <Link
                                        to="https://posthog.com/merch?product=posthog-plush-hedgehog"
                                        target="_blank"
                                        targetBlankIcon
                                    >
                                        welcome Max
                                        <br />
                                        to your home – in plush form
                                    </Link>
                                </>
                            }
                        >
                            <span className="inline-block cursor-help">
                                Max is now PostHog AI – a core part of PostHog.
                            </span>
                        </Tooltip>
                    ) : (
                        'Build something people want.'
                    )}
                </div>
            </div>
        </>
    )
}
