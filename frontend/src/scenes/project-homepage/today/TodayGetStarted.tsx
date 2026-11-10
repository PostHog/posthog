import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCircleDashed, IconGithub } from '@posthog/icons'
import {
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Spinner,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { TodayGetStartedStep, todayGetStartedLogic } from './todayGetStartedLogic'
import { TodayWizardCommand } from './TodayWizardCommand'

const STEP_COPY: Record<TodayGetStartedStep['key'], { title: string; description: string }> = {
    install: {
        title: 'Install PostHog',
        description: 'Run Wizard in the root folder of your app. The setup agent installs the SDK.',
    },
    github: {
        title: 'Connect GitHub',
        description: 'So PostHog can open pull requests for what it finds.',
    },
    invite: {
        title: 'Invite your team',
        description: 'Each teammate gets their own list of what needs them.',
    },
}

function StepAction({ step }: { step: TodayGetStartedStep }): JSX.Element | null {
    const { stepActed } = useActions(todayGetStartedLogic)
    switch (step.key) {
        case 'install':
            return (
                <Button
                    size="inline"
                    variant="link-muted"
                    className="TodayGetStarted__manual"
                    render={
                        <LinkPrimitive
                            to={urls.onboarding({
                                productKey: ProductKey.PRODUCT_ANALYTICS,
                                stepKey: OnboardingStepKey.INSTALL,
                            })}
                        />
                    }
                    onClick={() => stepActed('install', 'manual')}
                    data-attr="today-get-started-install-manual"
                >
                    Install manually
                </Button>
            )
        case 'github':
            return (
                <Button
                    size="sm"
                    variant="outline"
                    onClick={() => stepActed('github', 'connect')}
                    data-attr="today-get-started-github"
                >
                    <IconGithub />
                    Connect GitHub
                </Button>
            )
        case 'invite':
            return (
                <Button
                    size="sm"
                    variant="outline"
                    onClick={() => stepActed('invite', 'invite')}
                    data-attr="today-get-started-invite"
                >
                    Invite
                </Button>
            )
    }
}

export function TodayGetStarted(): JSX.Element {
    const { steps } = useValues(todayGetStartedLogic)
    const { stepActed } = useActions(todayGetStartedLogic)
    const nextKey = steps.find((step) => !step.done)?.key

    return (
        <ItemGroup className="TodayGetStarted" data-attr="today-get-started">
            {steps.map((step) => (
                <Item
                    key={step.key}
                    size="sm"
                    variant={step.key === nextKey ? 'outline' : step.done ? 'muted' : 'default'}
                    data-attr={`today-get-started-step-${step.key}`}
                >
                    <ItemMedia>
                        {step.done ? (
                            <IconCheckCircle className="TodayGetStarted__done" aria-label="Done" />
                        ) : (
                            <IconCircleDashed className="TodayGetStarted__todo" aria-hidden />
                        )}
                    </ItemMedia>
                    <ItemContent>
                        <ItemTitle className={step.done ? 'TodayGetStarted__doneTitle' : undefined}>
                            {STEP_COPY[step.key].title}
                        </ItemTitle>
                        {!step.done ? <ItemDescription>{STEP_COPY[step.key].description}</ItemDescription> : null}
                        {!step.done && step.key === 'install' ? (
                            <>
                                <TodayWizardCommand onCopy={() => stepActed('install', 'copy')} />
                                <div className="TodayGetStarted__installFooter">
                                    <span className="TodayGetStarted__waiting">
                                        <Spinner className="size-3" />
                                        <span>Waiting for your first event</span>
                                    </span>
                                    <StepAction step={step} />
                                </div>
                            </>
                        ) : null}
                    </ItemContent>
                    {!step.done && step.key !== 'install' ? (
                        <ItemActions>
                            <StepAction step={step} />
                        </ItemActions>
                    ) : null}
                </Item>
            ))}
        </ItemGroup>
    )
}
