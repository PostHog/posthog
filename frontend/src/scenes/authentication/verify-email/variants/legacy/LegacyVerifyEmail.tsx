import '../../VerifyEmail.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import * as shockedPng from '@posthog/brand/hoggies/png/shocked'
import { LemonButton, LemonCheckbox, LemonModal, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { HeartHog, MailHog } from 'lib/components/hedgehogs'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'
import { urls } from 'scenes/urls'

import { verifyEmailLogic } from '../../verifyEmailLogic'

const HedgehogShocked = pngHoggie(shockedPng)

interface SupportButtonsProps {
    disabledReason?: string
}

const SupportButtons = ({ disabledReason }: SupportButtonsProps): JSX.Element => {
    const { openSupportForm } = useActions(supportLogic)
    const { requestVerificationLink } = useActions(verifyEmailLogic)
    const { uuid } = useValues(verifyEmailLogic)

    return (
        <div className="flex flex-row gap-x-4 justify-start">
            <LemonButton
                type="primary"
                disabledReason={disabledReason}
                onClick={() => {
                    openSupportForm({ kind: 'bug', target_area: 'login' })
                }}
            >
                Contact support
            </LemonButton>
            {uuid && (
                <LemonButton
                    type="primary"
                    disabledReason={disabledReason}
                    onClick={() => {
                        requestVerificationLink(uuid)
                    }}
                >
                    Request a new link
                </LemonButton>
            )}
        </div>
    )
}

export const VerifyEmailHelpLinks = (): JSX.Element => {
    const [checkListValues, setCheckListValues] = useState<boolean[]>([])

    const checklist = [
        'Wait 5 minutes. Sometimes it takes a bit for email providers to deliver emails.',
        'Check your spam folder and any firewalls you may have active',
        'Ask your company IT department to allow any emails from @posthog.com',
        'Channel your inner hedgehog and take another peek at your inbox',
    ]

    const handleChecklistChange = (index: number): void => {
        const newCheckListValues = [...checkListValues]
        newCheckListValues[index] = !newCheckListValues[index]
        setCheckListValues(newCheckListValues)
    }

    const allChecked = checklist.every((_, index) => checkListValues[index])

    return (
        <div className="bg-primary p-4 rounded relative w-full max-w-160">
            <div className="flex flex-col justify-center">
                <div className="deprecated-space-y-2 text-left">
                    {checklist.map((item, index) => (
                        <LemonCheckbox
                            key={index}
                            onChange={() => handleChecklistChange(index)}
                            checked={checkListValues[index]}
                            label={item}
                            bordered
                            size="small"
                        />
                    ))}
                </div>
            </div>
            <div className="mt-4">
                <p className="text-left mb-2">Choose one of the following options:</p>
                <SupportButtons
                    disabledReason={!allChecked ? "Please confirm you've done all the steps above" : undefined}
                />
            </div>
        </div>
    )
}

const GetHelp = (): JSX.Element => {
    const [isOpen, setIsOpen] = useState(false)
    return (
        <>
            <LemonButton type="primary" onClick={() => setIsOpen(true)}>
                Get help
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title="Get help"
                description={
                    <p className="max-w-160">
                        Sorry you're having troubles! We're here to help, but first we ask that you check a few things
                        first on your end. Generally any issues with email happen after they leave our hands.
                    </p>
                }
            >
                <VerifyEmailHelpLinks />
            </LemonModal>
        </>
    )
}

function VerifyEmail(): JSX.Element {
    const { view } = useValues(verifyEmailLogic)

    return (
        <div className="flex h-full flex-col">
            <div className="flex h-full">
                <BridgePage view="verifyEmail" fixedWidth={false}>
                    <div className="px-12 py-8 text-center flex flex-col items-center max-w-160 w-full relative">
                        {view === 'pending' ? (
                            <>
                                <h2 className="text-lg">Welcome to PostHog!</h2>
                                <h1 className="text-3xl font-bold">Let's verify your email address.</h1>
                                <div className="max-w-60 my-10">
                                    <MailHog className="w-full h-full" />
                                </div>
                                <p className="mb-6">An email has been sent with a link to verify your email address.</p>
                                <GetHelp />
                            </>
                        ) : view === 'verify' ? (
                            <>
                                <Spinner className="text-4xl mb-12" />
                                <p>Verifying your email address...</p>
                            </>
                        ) : view === 'success' ? (
                            <>
                                <h1 className="text-3xl font-bold">Success!</h1>
                                <div className="max-w-60 mb-12">
                                    <HeartHog className="w-full h-full" />
                                </div>
                                <p>Thanks for verifying your email address. Now taking you to PostHog...</p>
                            </>
                        ) : view === 'invalid' ? (
                            <>
                                <h1 className="text-3xl font-bold">Whoops!</h1>
                                <div className="max-w-60 mb-12">
                                    <HedgehogShocked className="w-full h-full" />
                                </div>
                                <p className="mb-6">Seems like that link isn't quite right. Try again?</p>

                                <SupportButtons />

                                <p className="text-xs text-muted mt-6">
                                    If you've already verified your email, then{' '}
                                    <Link to={urls.login()}>log in here</Link>.
                                </p>
                            </>
                        ) : (
                            <Spinner className="text-4xl" />
                        )}
                        {view === 'success' && (
                            <div aria-hidden className="VerifyEmail__ProgressBar">
                                <div
                                    className={clsx('VerifyEmail__ProgressBarTrack', {
                                        'VerifyEmail__ProgressBarTrack--static':
                                            inStorybook() || inStorybookTestRunner(),
                                    })}
                                />
                            </div>
                        )}
                    </div>
                </BridgePage>
            </div>
        </div>
    )
}

export { VerifyEmail as LegacyVerifyEmail }
