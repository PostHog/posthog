import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

/** `consequence` finishes the sentence, for example "the debugger can't see its events." */
export function NoPagePosthogBanner({ consequence }: { consequence: string }): JSX.Element {
    return (
        <LemonBanner type="info">
            This page doesn't load posthog-js as <code>window.posthog</code>, so {consequence}
        </LemonBanner>
    )
}
