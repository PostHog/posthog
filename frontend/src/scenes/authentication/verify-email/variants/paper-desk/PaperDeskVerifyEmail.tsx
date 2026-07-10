import { useActions, useValues } from 'kea'
import { useState } from 'react'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'

import { pngHoggie } from 'lib/brand/hoggies'
import { ExplorerHog, SleepingHog } from 'lib/components/hedgehogs'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { PaperDeskCard, PaperDeskScene } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'
import { urls } from 'scenes/urls'

import { verifyEmailLogic } from '../../verifyEmailLogic'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

const NOTES: Record<string, string[]> = {
    pending: ['// one email away', '// we just hit send'],
    success: ['// verified', '// go explore'],
    invalid: ['// that link expired', '// happens to the best of us'],
    verify: ['// hold tight', '// verifying'],
}

const CHECKLIST = [
    'Wait 5 minutes, some email providers take a beat',
    'Check spam and any firewalls you run',
    'Channel your inner hedgehog and peek again',
]

function NotSeeingIt(): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)
    const { requestVerificationLink } = useActions(verifyEmailLogic)
    const { uuid, newlyRequestedVerificationLinkLoading } = useValues(verifyEmailLogic)
    const [open, setOpen] = useState(false)
    const [checked, setChecked] = useState<boolean[]>([])
    const allChecked = CHECKLIST.every((_, i) => checked[i])
    // Like legacy: the resend (and support) stay gated behind the checklist so they can't be spammed.
    const gateReason = !allChecked
        ? `Confirm the checks above (${checked.filter(Boolean).length}/${CHECKLIST.length})`
        : undefined

    return (
        <>
            <button
                type="button"
                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary text-xs"
                onClick={() => setOpen((v) => !v)}
            >
                Not seeing it?
            </button>
            {open && (
                <div className="PaperDesk__note mt-3 w-full py-3 px-3.5 text-xs leading-relaxed text-secondary text-left bg-[#fbfbf9] border border-dashed border-[#c5c6bd] rounded">
                    <p className="m-0 mb-2.5 font-semibold text-primary">Before we resend, three quick checks:</p>
                    <div className="flex flex-col gap-2">
                        {CHECKLIST.map((item, i) => (
                            <label key={i} className="flex items-start gap-2.5">
                                <input
                                    type="checkbox"
                                    checked={!!checked[i]}
                                    onChange={() =>
                                        setChecked((prev) => {
                                            const next = [...prev]
                                            next[i] = !next[i]
                                            return next
                                        })
                                    }
                                />
                                <span>{item}</span>
                            </label>
                        ))}
                    </div>
                    <div className="mt-3 flex flex-col gap-2">
                        {uuid && (
                            <LemonButton
                                type="primary"
                                size="large"
                                center
                                fullWidth
                                loading={newlyRequestedVerificationLinkLoading}
                                disabledReason={gateReason}
                                onClick={() => requestVerificationLink(uuid)}
                            >
                                Resend email
                            </LemonButton>
                        )}
                        <LemonButton
                            size="large"
                            center
                            fullWidth
                            disabledReason={gateReason}
                            onClick={() =>
                                openSupportForm({
                                    kind: 'bug',
                                    target_area: 'login',
                                })
                            }
                        >
                            Contact support
                        </LemonButton>
                    </div>
                </div>
            )}
        </>
    )
}

function VerifyEmail(): JSX.Element {
    const { view, uuid, newlyRequestedVerificationLinkLoading } = useValues(verifyEmailLogic)
    const { requestVerificationLink } = useActions(verifyEmailLogic)
    const { openSupportForm } = useActions(supportLogic)

    const notes = NOTES[view ?? 'pending'] ?? NOTES.pending

    if (view === 'success') {
        return (
            <PaperDeskScene notes={notes}>
                <PaperDeskCard>
                    <div className="flex flex-col items-center text-center">
                        <ExplorerHog className="block w-auto mx-auto h-32" />
                        <h1 className="m-0 mt-3 font-title text-2xl font-extrabold leading-tight text-primary text-center tracking-tight">
                            You're verified, go explore!
                        </h1>
                        <p className="PaperDesk__sub mt-2 mb-5 text-sm text-secondary text-center text-pretty">
                            Email confirmed. Next up: a quick setup. Your org, your team, your first events.
                        </p>
                        <div className="PaperDesk__progress mb-4 w-full h-1.5 overflow-hidden bg-[#e0e1d9] rounded-sm">
                            <div className="PaperDesk__progress-fill w-full h-full bg-warning rounded-sm" />
                        </div>
                        <p className="m-0 text-sm text-secondary text-center">Taking you to PostHog…</p>
                    </div>
                </PaperDeskCard>
            </PaperDeskScene>
        )
    }

    if (view === 'invalid') {
        return (
            <PaperDeskScene notes={notes}>
                <PaperDeskCard
                    footer={
                        <p className="mt-5 mb-0 text-sm text-secondary text-center">
                            Already verified?{' '}
                            <Link
                                to={urls.login()}
                                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                            >
                                Log in →
                            </Link>
                        </p>
                    }
                >
                    <div className="flex flex-col items-center text-center">
                        <SleepingHog className="block w-auto mx-auto h-28" />
                        <h1 className="m-0 mt-3 font-title text-2xl font-extrabold leading-tight text-primary text-center tracking-tight">
                            This link fell asleep
                        </h1>
                        <p className="PaperDesk__sub mt-2 mb-5 text-sm text-secondary text-center text-pretty">
                            Verification links last 24 hours, and this one's past its bedtime. Request a fresh one and
                            we'll get you in.
                        </p>
                        <div className="flex w-full flex-col gap-2.5">
                            {uuid && (
                                <LemonButton
                                    type="primary"
                                    size="large"
                                    center
                                    fullWidth
                                    loading={newlyRequestedVerificationLinkLoading}
                                    onClick={() => requestVerificationLink(uuid)}
                                >
                                    Email me a new link
                                </LemonButton>
                            )}
                            <LemonButton
                                size="large"
                                center
                                fullWidth
                                onClick={() =>
                                    openSupportForm({
                                        kind: 'bug',
                                        target_area: 'login',
                                    })
                                }
                            >
                                Contact support
                            </LemonButton>
                        </div>
                    </div>
                </PaperDeskCard>
            </PaperDeskScene>
        )
    }

    if (view === 'verify') {
        return (
            <PaperDeskScene notes={notes}>
                <PaperDeskCard>
                    <div className="flex flex-col items-center gap-4 text-center">
                        <Spinner className="text-4xl" />
                        <p className="PaperDesk__sub m-0 text-sm text-secondary text-center text-pretty">
                            Verifying your email address…
                        </p>
                    </div>
                </PaperDeskCard>
            </PaperDeskScene>
        )
    }

    // pending — check inbox
    return (
        <PaperDeskScene notes={notes}>
            <PaperDeskCard
                footer={
                    <p className="mt-5 mb-0 text-sm text-secondary text-center">
                        Wrong address?{' '}
                        <Link
                            to={urls.signup()}
                            className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                        >
                            Start over →
                        </Link>
                    </p>
                }
            >
                <div className="flex flex-col items-center text-center">
                    <HedgehogMagnifyingGlass className="block w-auto mx-auto h-28" />
                    <h1 className="m-0 mt-3 font-title text-2xl font-extrabold leading-tight text-primary text-center tracking-tight">
                        Check your inbox
                    </h1>
                    <p className="PaperDesk__sub mt-2 mb-4 text-sm text-secondary text-center text-pretty">
                        We sent you a verification link. Click the link inside and you're in. It's valid for 24 hours.
                    </p>
                    <NotSeeingIt />
                </div>
            </PaperDeskCard>
        </PaperDeskScene>
    )
}

export { VerifyEmail as PaperDeskVerifyEmail }
