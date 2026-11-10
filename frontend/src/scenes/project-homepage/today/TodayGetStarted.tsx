import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconGithub } from '@posthog/icons'
import {
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Progress,
    Text,
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
        description:
            'Run Wizard in the root folder of your app. The setup agent installs the SDK and captures your first events.',
    },
    github: {
        title: 'Connect GitHub',
        description: 'PostHog reads your code to explain what it finds, and can open pull requests to fix it.',
    },
    invite: {
        title: 'Invite your team',
        description: 'Teammates get their own list of what needs them each day.',
    },
}

function StepAction({ step }: { step: TodayGetStartedStep }): JSX.Element | null {
    const { stepActed } = useActions(todayGetStartedLogic)
    switch (step.key) {
        case 'install':
            return (
                <Button
                    size="sm"
                    variant="link-muted"
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
    const { steps, doneCount } = useValues(todayGetStartedLogic)
    const { stepActed, hideGuide } = useActions(todayGetStartedLogic)
    const nextKey = steps.find((step) => !step.done)?.key

    return (
        <div className="TodayGetStarted" data-attr="today-get-started">
            <div className="TodayGetStarted__header">
                <Text size="sm" weight="medium" render={<p />} className="m-0">
                    Set up PostHog
                </Text>
                <div className="flex items-center gap-2">
                    <Text size="xs" variant="muted" render={<span />} translate="no">
                        {`${doneCount} of ${steps.length} done`}
                    </Text>
                    <Button size="xs" variant="link-muted" onClick={hideGuide} data-attr="today-get-started-hide">
                        Hide
                    </Button>
                </div>
            </div>
            <Progress value={(doneCount / steps.length) * 100} aria-label="Setup progress" />
            <ItemGroup>
                {steps.map((step) => (
                    <Item
                        key={step.key}
                        size="sm"
                        variant={step.key === nextKey ? 'outline' : 'default'}
                        data-attr={`today-get-started-step-${step.key}`}
                    >
                        <ItemMedia>
                            {step.done ? (
                                <IconCheckCircle className="TodayGetStarted__done" aria-label="Done" />
                            ) : (
                                <span className="TodayGetStarted__todo" aria-hidden />
                            )}
                        </ItemMedia>
                        <ItemContent>
                            <ItemTitle className={step.done ? 'TodayGetStarted__doneTitle' : undefined}>
                                {STEP_COPY[step.key].title}
                            </ItemTitle>
                            {!step.done ? <ItemDescription>{STEP_COPY[step.key].description}</ItemDescription> : null}
                            {!step.done && step.key === 'install' ? (
                                <TodayWizardCommand onCopy={() => stepActed('install', 'copy')} />
                            ) : null}
                        </ItemContent>
                        {!step.done ? (
                            <ItemActions>
                                <StepAction step={step} />
                            </ItemActions>
                        ) : null}
                    </Item>
                ))}
            </ItemGroup>
        </div>
    )
}
