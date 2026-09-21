// Legacy PostHog hedgehog illustrations.
//
// ⚠️ We're migrating away from these hand-rolled hogs to the shared `@posthog/brand`
// hoggie library, rendered via its PNG exports — see `pngHoggie` in lib/brand/hoggies.
// Do NOT add new usages of anything exported here; reach for a `@posthog/brand` hoggie
// instead.
// Everything left below is still rendered somewhere, and stays only because
// `@posthog/brand` has no equivalent art for it yet. Each hog moves to the brand
// library once there is good art to replace it with, so the end state of this file is
// no local hedgehogs at all. The art requests are tracked by:
//   - https://github.com/PostHog/marketing/issues/154
//   - https://github.com/PostHog/marketing/issues/145
//   - https://github.com/PostHog/marketing/issues/146
//   - https://github.com/PostHog/marketing/issues/148
import React, { ImgHTMLAttributes } from 'react'

import climberHog1 from 'public/hedgehog/climber-hog-01.png'
import climberHog2 from 'public/hedgehog/climber-hog-02.png'
import hogWelder from 'public/hedgehog/hog-welder.png'
import sleepingHog from 'public/hedgehog/sleeping-hog.png'
import warningHog from 'public/hedgehog/warning-hog.png'
import wavingHog from 'public/hedgehog/waving-hog.png'

type HedgehogProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'>

// w400 x h400
const SquaredHedgehog = React.forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    function SquaredHedgehog(props, ref): JSX.Element {
        return <img src={props.src} width={400} height={400} alt="PostHog hedgehog" {...props} ref={ref} />
    }
)
// any width x h400
const RectangularHedgehog = React.forwardRef<HTMLImageElement, ImgHTMLAttributes<HTMLImageElement>>(
    function RectangularHedgehog(props, ref): JSX.Element {
        return <img src={props.src} height={400} alt="PostHog hedgehog" {...props} ref={ref} />
    }
)

/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const HogWelder = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={hogWelder} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const SleepingHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={sleepingHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const WarningHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={warningHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const WavingHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={wavingHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const ClimberHog1 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={climberHog1} width={378} height={417} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const ClimberHog2 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={climberHog2} width={518} height={1586} {...props} />
}
