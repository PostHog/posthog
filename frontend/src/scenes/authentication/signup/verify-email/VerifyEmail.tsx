import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { HeartHog, MailHog, SurprisedHog } from 'lib/components/hedgehogs'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { verifyEmailLogic } from './verifyEmailLogic'
import { SupportModal } from 'lib/components/Support/SupportModal'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { IconGmail, IconYahoo, IconOutlook, IconIcloud } from 'lib/lemon-ui/icons'

export const scene: SceneExport = {
    component: VerifyEmail,
    logic: verifyEmailLogic,
}

interface EmailProviderLinkProps {
    label: string
    icon: JSX.Element
    link: string
}

const EmailProviderLink: React.FC<EmailProviderLinkProps> = ({ label, icon, link }) => {
    const handleClick = (): void => {
        window.open(link, '_blank')
    }

    return (
        <LemonButton type="secondary" icon={icon} size="large" className="mt-4" onClick={handleClick}>
            {label}
        </LemonButton>
    )
}

export const VerifyEmailProvidersLinks = (): JSX.Element => {
    return (
        <div className="flex flex-row flex-wrap gap-x-3 justify-center">
            <EmailProviderLink
                label="Gmail"
                icon={<IconGmail />}
                link="https://mail.google.com/mail/u/0/#search/posthog"
            />
            <EmailProviderLink
                label="Yahoo"
                icon={<IconYahoo />}
                link="https://mail.yahoo.com/d/search/keyword=posthog"
            />
            <EmailProviderLink
                label="Outlook"
                icon={<IconOutlook />}
                link="https://outlook.live.com/mail/search?q=posthog"
            />
            <EmailProviderLink label="iCloud" icon={<IconIcloud />} link="https://www.icloud.com/mail" />
        </div>
    )
}

export const VerifyEmailHelpLinks = (): JSX.Element => {
    const { requestVerificationLink } = useActions(verifyEmailLogic)
    const { uuid } = useValues(verifyEmailLogic)
    const { openSupportLoggedOutForm } = useActions(supportLogic)

    return (
        <div className="flex flex-col flex-wrap items-center">
            <p className="mt-4">Using any of the following services? Click to quickly go to your email inbox.</p>
            <VerifyEmailProvidersLinks />
            <div className="flex flex-row flex-wrap gap-x-4 justify-center">
                <LemonButton
                    type="secondary"
                    className="mt-8"
                    onClick={() => {
                        openSupportLoggedOutForm(null, null, 'bug', 'login')
                    }}
                >
                    Contact support
                </LemonButton>
                {uuid && (
                    <LemonButton
                        type="secondary"
                        className="mt-8"
                        onClick={() => {
                            requestVerificationLink(uuid)
                        }}
                    >
                        Request a new link
                    </LemonButton>
                )}
                <SupportModal loggedIn={false} />
            </div>
        </div>
    )
}

export function VerifyEmail(): JSX.Element {
    const { view } = useValues(verifyEmailLogic)

    return (
        <div className="flex h-full flex-col">
            <div className="flex h-full">
                <BridgePage view="verifyEmail" fixedWidth={false} className="VerifyEmailContent">
                    <div className="px-12 py-8 text-center flex flex-col items-center max-w-200">
                        {view === 'pending' ? (
                            <>
                                <h1 className="text-xl">Welcome to PostHog!</h1>
                                <h1 className="text-3xl font-bold">Let's verify your email address.</h1>
                                <div className="max-w-80 my-12">
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
