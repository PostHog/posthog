import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { BuilderHog2 } from 'lib/components/hedgehogs'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'

export const scene: SceneExport = {
    component: VerifyEmail,
}

export function VerifyEmail(): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <div className="flex h-full flex-col">
            <div className="IngestionTopbar">
                <FriendlyLogo style={{ fontSize: '1.125rem' }} />
                <div className="flex">
                    <HelpButton />
                </div>
            </div>
            <div className="flex h-full">
                <BridgePage view="verifyEmail" noLogo fixedWidth={false} className="VerifyEmailContent p-32">
                    <div className="px-12 py-8 text-center flex flex-col items-center max-w-200">
                        <h1 className="text-xl">Welcome to PostHog!</h1>
                        <h1 className="text-3xl font-bold">Let's verify your email address.</h1>
                        <div className="max-w-80 mb-12">
                            <BuilderHog2 className="w-full h-full" />
                        </div>
                        <p>
                            An email has been sent to <span className="font-bold">{user?.email}</span> with a link to
                            verify your email address. If you have not received the email in a few minutes, please check
                            your spam folder.
                        </p>
                        <LemonButton type="secondary" className="mt-8" to={'mailto:hey@posthog.com'}>
                            Contact Support
                        </LemonButton>
                    </div>
                </BridgePage>
            </div>
        </div>
    )
}
