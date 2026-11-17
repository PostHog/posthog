import './SignupPasswordStrength.scss'

import { useEffect, useState } from 'react'
import type { ZXCVBNResult } from 'zxcvbn'

import { IconInfo, IconLock } from '@posthog/icons'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { HEDGEHOG_LIFETIME_SECONDS, hedgehogLifetimes } from './hedgehogLifetimes'

export function SignupPasswordStrength({ password }: { password: string }): JSX.Element {
    const [estimate, setEstimate] = useState<ZXCVBNResult | null>(null)
    const [unavailable, setUnavailable] = useState(false)
    const { ref: hedgehogsRef, width } = useResizeObserver<HTMLDivElement>()

    useEffect(() => {
        let canceled = false
        setUnavailable(false)
        if (password && password.length <= 72) {
            void import('zxcvbn')
                .then(({ default: zxcvbn }) => {
                    if (!canceled) {
                        setEstimate(zxcvbn(password))
                    }
                })
                .catch(() => {
                    if (!canceled) {
                        setEstimate(null)
                        setUnavailable(true)
                    }
                })
        } else {
            setEstimate(null)
        }
        return () => {
            canceled = true
        }
    }, [password])

    const crackTimeSeconds = estimate ? estimate.guesses / 1e10 : 0
    const lifetimes = crackTimeSeconds / HEDGEHOG_LIFETIME_SECONDS
    const capacity = Math.max(1, Math.floor(((width ?? 0) + 4) / 34)) * 2
    const visibleLifetimes = Math.min(Math.max(lifetimes, 0.5), capacity)
    const remainingHedgehogs = Math.max(0, Math.ceil(lifetimes) - capacity)
    const strength = estimate
        ? crackTimeSeconds < 24 * 60 * 60
            ? 'weak'
            : crackTimeSeconds < HEDGEHOG_LIFETIME_SECONDS / 3
              ? 'medium'
              : 'strong'
        : undefined

    return (
        <div id="signup-password-strength" className="SignupPasswordStrength flex items-center gap-3 py-2">
            <div className="flex flex-col gap-1 min-w-0 flex-1">
                <span className="flex items-center gap-1 text-xs text-secondary">
                    <IconLock aria-hidden />
                    <span>Estimated time to crack</span>
                </span>
                <div
                    className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1"
                    role="status"
                    aria-live="polite"
                    aria-atomic="true"
                >
                    <div className="inline-flex items-center gap-1">
                        <span
                            className="SignupPasswordStrength__headline font-semibold text-sm"
                            data-strength={strength}
                            aria-label={
                                estimate
                                    ? `${strength} password: ${hedgehogLifetimes(estimate.guesses / 1e10)}`
                                    : undefined
                            }
                        >
                            {password.length > 72
                                ? 'Use 72 characters or fewer'
                                : !password
                                  ? 'How long would a hedgehog need?'
                                  : unavailable
                                    ? 'Estimate unavailable'
                                    : estimate
                                      ? hedgehogLifetimes(estimate.guesses / 1e10)
                                      : 'Estimating…'}
                        </span>
                        {estimate && (
                            <Tooltip title="One hedgehog lifetime is 3 years. This estimates how long it would take to guess your password at 10 billion guesses per second. More lifetimes means a stronger password.">
                                <LemonButton
                                    type="tertiary"
                                    size="xsmall"
                                    noPadding
                                    icon={<IconInfo />}
                                    aria-label="About password strength in hedgehog lifetimes"
                                    data-attr="signup-password-strength-info"
                                />
                            </Tooltip>
                        )}
                    </div>
                    {estimate && (
                        <span className="text-xs text-secondary ml-auto">
                            {`or ${
                                lifetimes * 3 >= 100
                                    ? `${new Intl.NumberFormat('en-US', {
                                          notation: 'compact',
                                          compactDisplay: 'long',
                                          maximumSignificantDigits: 3,
                                      }).format(lifetimes * 3)} years`
                                    : estimate.crack_times_display.offline_fast_hashing_1e10_per_second
                            }`}
                        </span>
                    )}
                </div>
                <div className="SignupPasswordStrength__hedgehogs" ref={hedgehogsRef} aria-hidden>
                    {Array.from({ length: Math.ceil(visibleLifetimes) }, (_, index) => (
                        <span
                            key={index}
                            className="SignupPasswordStrength__hedgehog"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ clipPath: `inset(0 ${(1 - Math.min(1, visibleLifetimes - index)) * 100}% 0 0)` }}
                        />
                    ))}
                </div>
                {remainingHedgehogs > 0 && (
                    <span className="text-xs text-secondary">
                        {`and ${remainingHedgehogs.toLocaleString('en-US')} more hedgehogs`}
                    </span>
                )}
            </div>
        </div>
    )
}
