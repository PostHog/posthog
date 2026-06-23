import { useActions } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconBolt, IconCheck, IconGithub, IconNotebook, IconPause, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand/Logomark'
import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { cn } from 'lib/utils/css-classes'

import { inboxOnboardingLogic } from '../../logics/inboxOnboardingLogic'
import { PullRequestPreview, ReportPreview } from './InboxOnboardingPreviews'

/** The one command that sets up self-driving. The whole onboarding orbits this string. */
export const SELF_DRIVING_WIZARD_COMMAND = 'npx -y @posthog/wizard@latest self-driving'

/** What the wizard wires up, shown as a reassuring checklist under the command. */
const WIZARD_SETS_UP: { icon: JSX.Element; label: string }[] = [
    { icon: <IconGithub />, label: 'Connects your GitHub, so agents can open pull requests' },
    { icon: <IconBolt />, label: 'Picks the signal sources and scouts to watch' },
    { icon: <IconNotebook />, label: 'Brings shippable PRs and reports that need input here' },
]

interface Beat {
    label: string
    description: string
    preview: JSX.Element
}

const BEATS: Beat[] = [
    {
        label: 'Pull requests, ready to merge.',
        description:
            'Agents read your product data and open a PR for anything safe to ship – with the diff, tests, and reviewers already lined up.',
        preview: <PullRequestPreview />,
    },
    {
        label: 'Reports, when it needs your call.',
        description:
            "Not everything is a clean code change. When something needs your judgment, agents file a report with the context and what they'd do – you decide.",
        preview: <ReportPreview />,
    },
]

/**
 * The wizard command as a click-to-copy pill – the single call-to-action of the whole onboarding.
 * Reuses the shared `CommandBlock` (same one MCP install uses) with the `rainbow` AI gradient, so
 * it reads as "enable a capability" rather than a code dump.
 */
function SelfDrivingCommand({ size = 'md' }: { size?: 'sm' | 'md' }): JSX.Element {
    return (
        <CommandBlock
            command={SELF_DRIVING_WIZARD_COMMAND}
            copyLabel="self-driving setup command"
            ariaLabel="Copy self-driving setup command"
            decoration="rainbow"
            size={size}
            // rounded-md sits one step inside the rounded-lg card/banner it nests in.
            className="!m-0 rounded-md border border-primary bg-surface-secondary hover:border-accent"
        />
    )
}

function Hero(): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-3">
            <span className="flex items-center justify-center [&_svg]:h-7 [&_svg]:w-auto">
                <Logomark />
            </span>
            <h1 className="m-0 text-3xl font-bold leading-tight tracking-tight">Put your product on self-driving</h1>
            <p className="m-0 max-w-prose text-sm text-secondary leading-relaxed">
                <strong>Scouts and Signal Sources identify product issues and opportunities</strong>. Bugs in error
                tracking, users expressing their needs in Slack, and more.
                <br />
                <strong>PostHog then ships quality PRs for you to merge.</strong> Prioritized by impact, assigned to
                relevant team members. <u>The work lands right here in your Inbox.</u>
            </p>
        </div>
    )
}

function CommandCard(): JSX.Element {
    return (
        <div className="flex flex-col gap-3 rounded-lg border border-primary bg-surface-primary p-5">
            <div className="flex flex-col gap-0.5">
                <h2 className="m-0 text-base font-semibold">One command. That's the whole setup.</h2>
                <p className="m-0 text-sm text-secondary">
                    Run it in your project's repo – there are no in-app steps to click through.
                </p>
            </div>
            <SelfDrivingCommand size="md" />
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {WIZARD_SETS_UP.map((item) => (
                    <li key={item.label} className="flex items-center gap-2.5 text-sm text-secondary">
                        <span className="flex size-5 shrink-0 items-center justify-center rounded bg-surface-secondary text-default [&_svg]:size-3">
                            {item.icon}
                        </span>
                        <span className="min-w-0">{item.label}</span>
                        <IconCheck className="ml-auto size-4 shrink-0 text-success" />
                    </li>
                ))}
            </ul>
        </div>
    )
}

function BeatRow({ beat, index }: { beat: Beat; index: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-baseline gap-3">
                <span className="font-mono text-xs text-muted tabular-nums">0{index + 1}</span>
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-[15px] font-semibold leading-snug">{beat.label}</span>
                    <span className="max-w-prose text-[13px] text-secondary leading-snug">{beat.description}</span>
                </div>
            </div>
            {/* Real inbox cards, kept inert by the preview's click interception (it meeps instead). */}
            <div className="select-none pl-8">{beat.preview}</div>
        </div>
    )
}

/**
 * Vertical scroll container that softly fades content into transparency at whichever edge has more
 * to scroll to (top once scrolled down, bottom while there's more below) – a fade-in rather than a
 * hard cut or a drop shadow. The mask is a plain CSS gradient toggled by scroll position.
 */
function ScrollFade({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element {
    const scrollRef = useRef<HTMLDivElement>(null)
    const [fade, setFade] = useState({ top: false, bottom: false })

    const measure = useCallback((): void => {
        const el = scrollRef.current
        if (!el) {
            return
        }
        setFade({
            top: el.scrollTop > 1,
            bottom: Math.ceil(el.scrollTop + el.clientHeight) < el.scrollHeight - 1,
        })
    }, [])

    useEffect(() => {
        const el = scrollRef.current
        if (!el) {
            return
        }
        // Observe the container (viewport resizes) *and* its content child (late-rendering cards grow
        // it past the fixed-height container without the container itself resizing) so the initial
        // bottom fade shows before any scroll.
        const observer = new ResizeObserver(measure)
        observer.observe(el)
        if (el.firstElementChild) {
            observer.observe(el.firstElementChild)
        }
        return () => observer.disconnect()
    }, [measure])

    // Independent top/bottom stops joined in one gradient; the off-edge stop (black_0%/black_100%)
    // is a no-op, so this matches a hard edge when that side isn't faded.
    const topStop = fade.top ? 'transparent,black_24px' : 'black_0%'
    const bottomStop = fade.bottom ? 'black_calc(100%-24px),transparent' : 'black_100%'
    const mask = fade.top || fade.bottom ? `[mask-image:linear-gradient(to_bottom,${topStop},${bottomStop})]` : ''

    return (
        <div ref={scrollRef} onScroll={measure} className={cn('overflow-auto', mask, className)}>
            {children}
        </div>
    )
}

/**
 * Full-pane self-driving onboarding takeover, shown in place of the inbox tabs when self-driving
 * isn't set up and there's nothing in the inbox yet. Sells the payoff (pull requests to ship,
 * reports that need your call) and centers the single wizard command. No skip – nothing behind it.
 */
export function InboxOnboardingTakeover(): JSX.Element {
    return (
        <ScrollFade className="flex-1 min-h-0">
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-8">
                <Hero />
                <CommandCard />
                <div className="flex flex-col gap-7">
                    {BEATS.map((beat, index) => (
                        <BeatRow key={beat.label} beat={beat} index={index} />
                    ))}
                </div>
            </div>
        </ScrollFade>
    )
}

/**
 * Sleek, non-blocking nudge shown above the inbox when self-driving isn't set up but reports or
 * PRs already exist (they had sources/scouts before). Keeps full access to existing work while
 * enticing a re-enable via the same one command. Styled as an "enable a capability" card (à la the
 * MCP use-case hint) rather than a system banner; session-dismissable via the close button.
 */
export function InboxOnboardingBanner(): JSX.Element {
    const { dismissBanner } = useActions(inboxOnboardingLogic)

    return (
        <div className="mx-4 mb-3 mt-2 flex flex-col gap-2 rounded-lg border border-dashed border-primary bg-bg-light p-4">
            <div className="flex items-center gap-2 -my-1">
                <IconPause className="size-4 shrink-0 text-accent" />
                <h4 className="m-0 flex-1 text-sm font-semibold">Self-driving is paused</h4>
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    tooltip="Dismiss for now"
                    aria-label="Dismiss self-driving reminder"
                    onClick={dismissBanner}
                />
            </div>
            <p className="mb-0.5 text-sm text-tertiary">
                No scouts or sources are enabled right now.{' '}
                <strong>Switch self-driving back on with one command in your product's repo:</strong>
            </p>
            <SelfDrivingCommand size="sm" />
        </div>
    )
}
