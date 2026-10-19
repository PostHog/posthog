import { useValues } from 'kea'

import { DialogDescription, DialogHeader, DialogTitle, Highlight } from '@posthog/quill'

import { welcomeDialogLogic } from 'scenes/welcome/welcomeDialogLogic'

import { waysToUseLogic } from './waysToUseLogic'

export function WaysToUseDialogHeader(): JSX.Element {
    const { variant, currentStep, steps } = useValues(waysToUseLogic)
    const { organizationName, inviter } = useValues(welcomeDialogLogic)
    const welcome = variant === 'invitee' && (currentStep === 'team' || steps.length === 1)
    const invitedBy = inviter ? `${inviter.name.split(' ')[0]} invited you. ` : ''

    return (
        <DialogHeader className="items-center text-center">
            {welcome ? (
                <>
                    <DialogTitle className="text-lg">
                        Welcome to{' '}
                        <Highlight animate delay={300}>
                            {organizationName || 'your team'}
                        </Highlight>
                    </DialogTitle>
                    <DialogDescription className="max-w-xl text-balance">
                        {`${invitedBy}${currentStep === 'team' ? 'Here is what your team works on.' : 'Use PostHog wherever you work.'}`}
                    </DialogDescription>
                </>
            ) : (
                <>
                    <DialogTitle className="text-lg">
                        PostHog,{' '}
                        <Highlight animate delay={300}>
                            wherever you work
                        </Highlight>
                    </DialogTitle>
                    <DialogDescription className="max-w-xl text-balance">
                        Bring your product data into the tools you already use.
                    </DialogDescription>
                </>
            )}
        </DialogHeader>
    )
}
