import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconArrowRight, IconCheck, IconChevronDown, IconPeople, IconSend, IconTerminal } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'

import { onboardingLogic } from '../onboardingLogic'
import { installStepLogic } from './installStepLogic'

const DELEGATE_BENEFITS = ['One-line install link', 'SDK docs & wizard command', 'No seat required']

/** Step 2: get PostHog into the product — run the wizard, delegate to a developer, or switch to the use-only track. */
export function InstallStep(): JSX.Element {
    const { name, organizationName } = useValues(onboardingLogic)
    const { setTrack } = useActions(onboardingLogic)
    const { delegateOpen, delegateEmail, isSubmitting, sent, canSubmitDelegation } = useValues(installStepLogic)
    const { setDelegateOpen, setDelegateEmail, submitDelegation } = useActions(installStepLogic)
    // The `npx @posthog/wizard` CLI only targets cloud/dev; hide the card entirely otherwise.
    const { wizardCommand, isCloudOrDev } = useWizardCommand()

    const firstName = name.trim().split(' ')[0]
    const orgName = organizationName.trim()

    return (
        <div className="max-w-2xl">
            <div className="text-accent text-xs font-bold uppercase tracking-wider">
                Welcome{firstName ? `, ${firstName}` : ''}
            </div>
            <h1 className="mt-2 text-3xl font-bold text-default">
                {orgName
                    ? `Now let's get PostHog into ${orgName}'s product.`
                    : "Now let's get PostHog into your product."}
            </h1>
            <p className="text-secondary mt-2">
                Pick how you want to install — the setup wizard does the work either way. Keep onboarding while it runs.
            </p>

            {/* Primary: run the setup wizard locally */}
            {isCloudOrDev && (
                <div className="mt-6 rounded-lg border border-primary bg-surface-primary p-4 sm:p-5">
                    <div className="flex items-center gap-2">
                        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary">
                            <IconTerminal className="text-lg text-default" />
                        </span>
                        <h2 className="m-0 text-base font-semibold text-default">Run the setup wizard</h2>
                        <span className="text-muted rounded bg-surface-secondary px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide">
                            CLI
                        </span>
                    </div>
                    <p className="text-secondary mb-0 mt-2 text-sm">
                        One command in your terminal. It detects your stack, installs the SDKs and instruments key
                        events.
                    </p>
                    <div className="mt-4">
                        <CommandBlock
                            command={wizardCommand}
                            copyLabel="Wizard command"
                            ariaLabel="Copy the PostHog setup wizard command"
                            size="md"
                            decoration="rainbow"
                            className="bg-surface-secondary border border-primary hover:border-accent"
                        />
                    </div>
                </div>
            )}

            {/* Fork: delegate to a developer, or switch to the use-only track */}
            <button
                type="button"
                onClick={() => setDelegateOpen(!delegateOpen)}
                className="mt-4 flex w-full items-center gap-3 rounded-lg border border-primary bg-surface-primary p-3 text-left transition-colors hover:border-accent"
            >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-secondary">
                    <IconPeople className="text-muted text-lg" />
                </span>
                <span className="flex-1">
                    <span className="block font-semibold text-default">I'm not the one who installs</span>
                    <span className="text-secondary block text-xs">
                        Delegate it to a developer, or you're just here to use PostHog.
                    </span>
                </span>
                <IconChevronDown
                    className={clsx('text-muted shrink-0 transition-transform', delegateOpen && 'rotate-180')}
                />
            </button>

            {delegateOpen && (
                <div className="mt-3 overflow-hidden rounded-lg border border-primary bg-surface-primary">
                    <div className="p-4 sm:p-5">
                        <div className="flex gap-3">
                            <span className="text-accent flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface-secondary">
                                <IconSend className="text-lg" />
                            </span>
                            <div>
                                <h3 className="m-0 font-semibold text-default">Delegate install to a developer</h3>
                                <p className="text-secondary m-0 mt-1 text-sm">
                                    Send the setup wizard to whoever owns the codebase. They don't need a PostHog seat.
                                </p>
                            </div>
                        </div>

                        {sent ? (
                            <div className="text-success mt-4 flex items-center gap-2 text-sm font-semibold">
                                <IconCheck /> Invitation sent — they'll get setup instructions by email.
                            </div>
                        ) : (
                            <form
                                className="mt-4 flex flex-col gap-2 sm:flex-row"
                                onSubmit={(e) => {
                                    e.preventDefault()
                                    submitDelegation()
                                }}
                            >
                                <LemonInput
                                    type="email"
                                    className="flex-1"
                                    value={delegateEmail}
                                    onChange={setDelegateEmail}
                                    placeholder="developer@yourcompany.com"
                                    autoFocus
                                />
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    loading={isSubmitting}
                                    disabledReason={
                                        !canSubmitDelegation && !isSubmitting
                                            ? 'Enter a valid email address'
                                            : undefined
                                    }
                                >
                                    Send invite
                                </LemonButton>
                            </form>
                        )}

                        <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5">
                            {DELEGATE_BENEFITS.map((benefit) => (
                                <span key={benefit} className="text-secondary inline-flex items-center gap-1.5 text-xs">
                                    <IconCheck className="text-success" /> {benefit}
                                </span>
                            ))}
                        </div>
                    </div>

                    {/* Use-only path */}
                    <div className="flex flex-wrap items-center gap-3 border-t border-primary bg-surface-secondary px-4 py-3 sm:px-5">
                        <span className="text-secondary flex-1 text-sm">
                            Prefer to explore first? We'll skip install and onboard you to{' '}
                            <span className="font-semibold text-default">use</span> PostHog.
                        </span>
                        <LemonButton
                            type="secondary"
                            size="small"
                            sideIcon={<IconArrowRight />}
                            onClick={() => setTrack('user')}
                        >
                            Onboard me to use it
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
