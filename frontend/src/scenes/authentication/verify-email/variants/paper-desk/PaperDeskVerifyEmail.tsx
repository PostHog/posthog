import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { DetectiveHog, ExplorerHog, SleepingHog } from 'lib/components/hedgehogs'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import {
    PaperFooterNote,
    PaperLink,
    PaperPrimaryButton,
    PaperSecondaryButton,
} from 'scenes/authentication/shared/paperDesk/PaperDeskControls'
import { PaperDeskCard, PaperDeskScene } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'
import { urls } from 'scenes/urls'

import { verifyEmailLogic } from '../../verifyEmailLogic'

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
    const [open, setOpen] = useState(false)
    const [checked, setChecked] = useState<boolean[]>([])
    const allChecked = CHECKLIST.every((_, i) => checked[i])

    return (
        <>
            <button
                type="button"
                className="PaperDesk__link PaperDesk__link--muted text-[12.5px]"
                onClick={() => setOpen((v) => !v)}
            >
                Not seeing it?
            </button>
            {open && (
                <div className="PaperDesk__note mt-3 w-full">
                    <p className="m-0 mb-2.5 font-semibold text-primary">Before we escalate, three quick checks:</p>
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
                    <PaperSecondaryButton
                        className="mt-3"
                        disabled={!allChecked}
                        onClick={() => openSupportForm({ kind: 'bug', target_area: 'login' })}
                    >
                        {allChecked
                            ? 'Contact support'
                            : `Contact support (${checked.filter(Boolean).length}/3 checked)`}
                    </PaperSecondaryButton>
                </div>
            )}
        </>
    )
}

function VerifyEmail(): JSX.Element {
    const { view, uuid, user } = useValues(verifyEmailLogic)
    const { requestVerificationLink } = useActions(verifyEmailLogic)
    const { openSupportForm } = useActions(supportLogic)

    const notes = NOTES[view ?? 'pending'] ?? NOTES.pending

    if (view === 'success') {
        return (
            <PaperDeskScene notes={notes}>
                <PaperDeskCard>
                    <div className="flex flex-col items-center text-center">
                        <ExplorerHog className="PaperDesk__hog h-[124px]" />
                        <h1 className="PaperDesk__title mt-3">You're verified, go explore!</h1>
                        <p className="PaperDesk__sub mb-5">
                            Email confirmed. Next up: a quick setup. Your org, your team, your first events.
                        </p>
                        <div className="PaperDesk__progress mb-[18px] w-full">
                            <div className="PaperDesk__progress-fill" />
                        </div>
                        <PaperPrimaryButton
                            htmlType="button"
                            onClick={() => {
                                window.location.href = '/'
                            }}
                        >
                            Continue to setup →
                        </PaperPrimaryButton>
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
                        <PaperFooterNote>
                            Already verified? <PaperLink to={urls.login()}>Log in →</PaperLink>
                        </PaperFooterNote>
                    }
                >
                    <div className="flex flex-col items-center text-center">
                        <SleepingHog className="PaperDesk__hog h-[104px]" />
                        <h1 className="PaperDesk__title mt-3">This link fell asleep</h1>
                        <p className="PaperDesk__sub mb-5">
                            Verification links last 24 hours, and this one's past its bedtime. Request a fresh one and
                            we'll get you in.
                        </p>
                        <div className="flex w-full flex-col gap-2.5">
                            {uuid && (
                                <PaperPrimaryButton htmlType="button" onClick={() => requestVerificationLink(uuid)}>
                                    Email me a new link
                                </PaperPrimaryButton>
                            )}
                            <PaperSecondaryButton
                                onClick={() => openSupportForm({ kind: 'bug', target_area: 'login' })}
                            >
                                Contact support
                            </PaperSecondaryButton>
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
                        <p className="PaperDesk__sub m-0">Verifying your email address…</p>
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
                    <PaperFooterNote>
                        Wrong address? <PaperLink to={urls.signup()}>Start over →</PaperLink>
                    </PaperFooterNote>
                }
            >
                <div className="flex flex-col items-center text-center">
                    <DetectiveHog className="PaperDesk__hog h-28" />
                    <h1 className="PaperDesk__title mt-3">Check your inbox</h1>
                    <p className="PaperDesk__sub mb-2.5">We sent a verification link to</p>
                    {user?.email && <span className="PaperDesk__emailChip mb-[18px]">{user.email}</span>}
                    <p className="PaperDesk__sub mt-0 mb-[18px]">
                        Click the link inside and you're in. The link is valid for 24 hours.
                    </p>
                    {uuid && (
                        <PaperSecondaryButton onClick={() => requestVerificationLink(uuid)}>
                            Resend email
                        </PaperSecondaryButton>
                    )}
                    <div className="mt-3.5">
                        <NotSeeingIt />
                    </div>
                </div>
            </PaperDeskCard>
        </PaperDeskScene>
    )
}

export { VerifyEmail as PaperDeskVerifyEmail }
