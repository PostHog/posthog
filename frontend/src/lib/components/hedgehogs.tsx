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
//   - https://github.com/PostHog/marketing/issues/148
import React, { ImgHTMLAttributes } from 'react'

import hogWelder from 'public/hedgehog/hog-welder.png'

type HedgehogProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'>

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
