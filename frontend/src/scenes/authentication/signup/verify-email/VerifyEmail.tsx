import { IconX } from '@posthog/icons'
import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { HeartHog, MailHog, SurprisedHog } from 'lib/components/hedgehogs'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { verifyEmailLogic } from './verifyEmailLogic'

export const scene: SceneExport = {
    component: VerifyEmail,
    logic: verifyEmailLogic,
}

export const VerifyEmailHelpLinks = (): JSX.Element => {
    const { requestVerificationLink } = useActions(verifyEmailLogic)
    const { uuid } = useValues(verifyEmailLogic)
    const { openSupportForm } = useActions(supportLogic)
    const [iNeedHelp, setINeedHelp] = useState(false)
    const [checkListValues, setCheckListValues] = useState<boolean[]>([])

    if (!iNeedHelp) {
        return (
            <LemonButton type="secondary" className="mt-2" onClick={() => setINeedHelp(true)}>
                I need help
            </LemonButton>
        )
    }

    const checklist = ['Checked your spam folder', 'Checked with your IT department (if applicable)']

    const handleChecklistChange = (index: number): void => {
        const newCheckListValues = [...checkListValues]
        newCheckListValues[index] = !newCheckListValues[index]
        setCheckListValues(newCheckListValues)
    }

    const allChecked = checklist.every((_, index) => checkListValues[index])

    return (
        <div className="w-full bg-bg-3000 p-4 rounded relative">
            <IconX
                className="absolute top-3 right-3 cursor-pointer"
                onClick={() => {
                    setCheckListValues([])
                    setINeedHelp(false)
                }}
            />
            <div className="flex flex-col justify-center">
                <p className="text-left mb-2">Please confirm you've done the following:</p>
                <div className="space-y-2">
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
            {allChecked && (
                <div className="mt-4">
                    <p className="text-left mb-2">Choose one of the following options:</p>
                    <div className="flex flex-row gap-x-4 justify-start">
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                openSupportForm({ kind: 'bug', target_area: 'login' })
                            }}
                        >
                            Contact support
                        </LemonButton>
                        {uuid && (
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    requestVerificationLink(uuid)
                                }}
                            >
                                Request a new link
                            </LemonButton>
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}

export function VerifyEmail(): JSX.Element {
    const { view } = useValues(verifyEmailLogic)

    return (
        <div className="flex h-full flex-col">
            <div className="flex h-full">
                <BridgePage view="verifyEmail" fixedWidth={false}>
                    <div className="px-12 py-8 text-center flex flex-col items-center max-w-160">
                        {view === 'pending' ? (
                            <>
                                <h1 className="text-xl">Welcome to PostHog!</h1>
                                <h1 className="text-3xl font-bold">Let's verify your email address.</h1>
                                <div className="max-w-60 my-10">
                                    <MailHog className="w-full h-full" />
                                </div>
                                <p>
                                    An email has been sent to with a link to verify your email address. If you have not
                                    received the email in a few minutes, please check your spam folder.
                                </p>
                                <VerifyEmailHelpLinks />
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
                                    <SurprisedHog className="w-full h-full" />
                                </div>
                                <p>Seems like that link isn't quite right. Try again?</p>
                                <VerifyEmailHelpLinks />
                            </>
                        ) : (
                            <Spinner className="text-4xl" />
                        )}
                    </div>
                </BridgePage>
            </div>
        </div>
    )
}
