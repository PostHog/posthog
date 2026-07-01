// Legacy PostHog hedgehog illustrations.
//
// ⚠️ We're migrating away from these hand-rolled hogs to the shared `@posthog/brand`
// hoggie library — `import { Hedgehog... } from '@posthog/brand/hoggies'`. Do NOT add
// new usages of anything exported here; reach for a `@posthog/brand` hoggie instead.
// Everything left below is still rendered somewhere, and we'll slowly remove all of
// them as the remaining usages are migrated over. Tracked by:
//   - https://github.com/PostHog/posthog.com/issues/17972
//   - https://github.com/PostHog/posthog.com/issues/17973
//   - https://github.com/PostHog/posthog.com/issues/17974
//   - https://github.com/PostHog/posthog.com/issues/17975
//   - https://github.com/PostHog/posthog.com/issues/17976
//   - https://github.com/PostHog/posthog.com/issues/17977
//   - https://github.com/PostHog/posthog.com/issues/17978
//   - https://github.com/PostHog/posthog.com/issues/17979
//   - https://github.com/PostHog/posthog.com/issues/17980
//   - https://github.com/PostHog/posthog.com/issues/17981
//   - https://github.com/PostHog/posthog.com/issues/17982
//   - https://github.com/PostHog/posthog.com/issues/17983
import React, { ImgHTMLAttributes } from 'react'

import bigLeaguesHog from 'public/hedgehog/big-leagues.png'
import burningMoneyHog from 'public/hedgehog/burning-money-hog.png'
import climberHog1 from 'public/hedgehog/climber-hog-01.png'
import climberHog2 from 'public/hedgehog/climber-hog-02.png'
import explorerHog from 'public/hedgehog/explorer-hog.png'
import featureFlagHog from 'public/hedgehog/feature-flag-hog.png'
import heartHog from 'public/hedgehog/heart-hog.png'
import hogWelder from 'public/hedgehog/hog-welder.png'
import mailHog from 'public/hedgehog/mail-hog.png'
import sleepingHog from 'public/hedgehog/sleeping-hog.png'
import starHog from 'public/hedgehog/star-hog.png'
import supermanHog from 'public/hedgehog/superman-hog.png'
import supportHeroHog from 'public/hedgehog/support-hero-hog.png'
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
export const ExplorerHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={explorerHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const HeartHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={heartHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const StarHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={starHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const SleepingHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={sleepingHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const SupportHeroHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={supportHeroHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const MailHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={mailHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const FeatureFlagHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={featureFlagHog} {...props} />
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
export const BurningMoneyHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={burningMoneyHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const SupermanHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={supermanHog} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const ClimberHog1 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={climberHog1} width={378} height={417} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const ClimberHog2 = (props: HedgehogProps): JSX.Element => {
    return <RectangularHedgehog src={climberHog2} width={518} height={1586} {...props} />
}
/** @deprecated Migrating to `@posthog/brand` (see file header) — don't add new usages. */
export const BigLeaguesHog = (props: HedgehogProps): JSX.Element => {
    return <SquaredHedgehog src={bigLeaguesHog} {...props} />
}
