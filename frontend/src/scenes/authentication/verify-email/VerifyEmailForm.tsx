import { useActions, useValues } from 'kea'
import { useState } from 'react'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-1'

import { pngHoggie } from 'lib/brand/hoggies'
import { ExplorerHog, SleepingHog } from 'lib/components/hedgehogs'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { getPendingVerificationEmail, isValidVerificationCode } from 'scenes/authentication/shared/verificationCode'
import { VerificationCodeInput } from 'scenes/authentication/shared/VerificationCodeInput'
import { urls } from 'scenes/urls'

import { verifyEmailLogic } from './verifyEmailLogic'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

const NOTES: Record<string, string[]> = {
    pending: ['// one email away', '// we just hit send'],
    success: ['// verified', '// go explore'],
    invalid: ['// nothing to verify', "// let's start again"],
}

const CHECKLIST = [
    'Wait 5 minutes, some email providers take a beat',
    'Check spam and any firewalls you run',
    'Channel your inner hedgehog and peek again',
]

function NotSeeingIt(): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)
    const { requestVerificationCode } = useActions(verifyEmailLogic)
    const { uuid, newlyRequestedVerificationCodeLoading } = useValues(verifyEmailLogic)
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
                <div className="AuthScene__note mt-3 w-full py-3 px-3.5 text-xs leading-relaxed text-secondary text-left bg-[#fbfbf9] border border-dashed border-[#c5c6bd] rounded">
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
                                loading={newlyRequestedVerificationCodeLoading}
                                disabledReason={gateReason}
                                onClick={() => requestVerificationCode(uuid)}
                            >
                                Resend code
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

function VerificationCodeEntry(): JSX.Element {
    const { verificationCode, verificationCodeError, verificationResultLoading } = useValues(verifyEmailLogic)
    const { setVerificationCode, submitVerificationCode } = useActions(verifyEmailLogic)

    return (
        <form
            className="flex w-full flex-col gap-2.5"
            // The code input renders a hidden input with a \d{6} pattern. Without noValidate,
            // the browser blocks an Enter-key submit on a partial code and shows no feedback.
            noValidate
            onSubmit={(e) => {
                e.preventDefault()
                if (!verificationResultLoading) {
                    submitVerificationCode()
                }
            }}
        >
            <VerificationCodeInput
                value={verificationCode}
                onChange={setVerificationCode}
                onComplete={() => {
                    if (!verificationResultLoading) {
                        submitVerificationCode()
                    }
                }}
                disabled={verificationResultLoading}
                data-attr="verify-email-code"
                status={verificationCodeError ? 'danger' : 'default'}
            />
            {verificationCodeError && (
                <p className="m-0 text-sm text-danger" role="alert">
                    {verificationCodeError}
                </p>
            )}
            <LemonButton
                type="primary"
                size="large"
                center
                fullWidth
                htmlType="submit"
                loading={verificationResultLoading}
                disabledReason={
                    isValidVerificationCode(verificationCode) ? undefined : 'Enter the 6-digit code from your email'
                }
                data-attr="verify-email-code-submit"
            >
                Verify email
            </LemonButton>
        </form>
    )
}

export function VerifyEmailForm(): JSX.Element {
    const { view, uuid, user } = useValues(verifyEmailLogic)
    const { openSupportForm } = useActions(supportLogic)

    const notes = NOTES[view ?? 'pending'] ?? NOTES.pending
    // The address that received the code. This is the new address if an email change is pending,
    // else the account address. Without a session, for example on a fresh signup, the page uses the
    // address the signup or login form stored in this browser. It stays unset in a different browser.
    const verificationEmail = user?.pending_email ?? user?.email ?? getPendingVerificationEmail(uuid) ?? undefined

    if (view === 'success') {
        return (
            <AuthScene notes={notes}>
                <AuthSceneCard>
                    <div className="flex flex-col items-center text-center">
                        <ExplorerHog className="block w-auto mx-auto h-32" />
                        <h1 className="m-0 mt-3 font-title text-2xl font-extrabold leading-tight text-primary text-center tracking-tight">
                            You're verified, go explore!
                        </h1>
                        <p className="AuthScene__sub mt-2 mb-5 text-sm text-secondary text-center text-pretty">
                            Email confirmed. Next up: a quick setup. Your org, your team, your first events.
                        </p>
                        <div className="AuthScene__progress mb-4 w-full h-1.5 overflow-hidden bg-[#e0e1d9] rounded-sm">
                            <div className="AuthScene__progress-fill w-full h-full bg-warning rounded-sm" />
                        </div>
                        <p className="m-0 text-sm text-secondary text-center">Taking you to PostHog…</p>
                    </div>
                </AuthSceneCard>
            </AuthScene>
        )
    }

    if (view === 'invalid') {
        return (
            <AuthScene notes={notes}>
                <AuthSceneCard
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
                            We don't know who to verify
                        </h1>
                        <p className="AuthScene__sub mt-2 mb-5 text-sm text-secondary text-center text-pretty">
                            Log in with your email and password and we'll send a new code to your inbox.
                        </p>
                        <div className="flex w-full flex-col gap-2.5">
                            <LemonButton type="primary" size="large" center fullWidth to={urls.login()}>
                                Log in
                            </LemonButton>
                            <LemonButton
                                size="large"
                                center
                                fullWidth
                                onClick={() =>
                                    openSupportForm({
                                        kind: 'bug',
                                    })
                                }
                            >
                                Contact support
                            </LemonButton>
                        </div>
                    </div>
                </AuthSceneCard>
            </AuthScene>
        )
    }

    // pending — check inbox
    return (
        <AuthScene notes={notes}>
            <AuthSceneCard
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
                    <p className="AuthScene__sub mt-2 mb-4 text-sm text-secondary text-center text-pretty">
                        {verificationEmail ? (
                            <>
                                We sent a 6-digit code to <strong>{verificationEmail}</strong>.
                                <br />
                                It's valid for 30 minutes.
                            </>
                        ) : (
                            <>We sent you a 6-digit code. It's valid for 30 minutes.</>
                        )}
                    </p>
                    <VerificationCodeEntry />
                    <div className="mt-3">
                        <NotSeeingIt />
                    </div>
                </div>
            </AuthSceneCard>
        </AuthScene>
    )
}
