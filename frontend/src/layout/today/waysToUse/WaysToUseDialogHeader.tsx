import { useValues } from 'kea'

import { DialogDescription, DialogHeader, DialogTitle, Highlight, Text } from '@posthog/quill'

import { welcomeDialogLogic } from 'scenes/welcome/welcomeDialogLogic'

import { TaskUserAvatar } from 'products/tasks/frontend/spaces/TaskUserAvatar'

import { waysToUseLogic } from './waysToUseLogic'

export function WaysToUseDialogHeader(): JSX.Element {
    const { variant, currentStep, steps } = useValues(waysToUseLogic)
    const { organizationName, inviter } = useValues(welcomeDialogLogic)
    const welcome = variant === 'invitee' && (currentStep === 'team' || steps.length === 1)

    if (!welcome) {
        return (
            <DialogHeader className="items-center text-center">
                <DialogTitle className="text-lg">
                    PostHog,{' '}
                    <Highlight animate delay={300}>
                        wherever you work
                    </Highlight>
                </DialogTitle>
                <DialogDescription className="max-w-xl text-balance">
                    Bring your product data into the tools you already use.
                </DialogDescription>
            </DialogHeader>
        )
    }

    return (
        <DialogHeader className="items-center gap-2 text-center">
            {inviter && (
                <div className="flex items-center gap-1.5" data-attr="today-ways-to-use-inviter">
                    <TaskUserAvatar user={{ first_name: inviter.name, last_name: '', email: inviter.email }} />
                    <Text size="xs" variant="muted" render={<span />}>
                        {`${inviter.name.split(' ')[0]} invited you`}
                    </Text>
                </div>
            )}
            <DialogTitle className="text-lg">
                Welcome to{' '}
                <Highlight animate delay={300}>
                    {organizationName || 'your team'}
                </Highlight>
            </DialogTitle>
            <DialogDescription className="max-w-xl text-balance">
                {steps.length > 1
                    ? 'Start with what your team already built, then pick where you use PostHog.'
                    : 'Pick where you use PostHog: the web app, Slack, or your coding agent.'}
            </DialogDescription>
        </DialogHeader>
    )
}
