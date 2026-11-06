import { useActions, useValues } from 'kea'

import { IconCloud, IconCode, IconSparkles, IconTerminal } from '@posthog/icons'
import { Button, Text } from '@posthog/quill'

import { MCP_INSTALL_COMMAND } from 'lib/components/MCPHint/constants'
import { useInterval } from 'lib/hooks/useInterval'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { useWizardCommand } from 'lib/onboarding/useWizardCommand'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { type Choice, ChoiceList } from '../components/ChoiceList'
import { CloudRunPanel } from '../components/CloudRunPanel'
import { CopyBlock } from '../components/CopyBlock'
import { InstallChecklist } from '../components/InstallChecklist'
import { StepLayout } from '../components/StepLayout'
import { agentInstallPrompt } from '../focusOptions'
import { type InstallMethod, guidedOnboardingLogic } from '../guidedOnboardingLogic'

const WIZARD_METHODS: Choice<InstallMethod>[] = [
    {
        value: 'cloud',
        title: 'Wizard in the cloud',
        description: 'The setup agent runs on our side and opens a pull request in your GitHub repository.',
        icon: <IconCloud />,
    },
    {
        value: 'wizard',
        title: 'Wizard on your machine',
        description: 'Run one command in your project folder. The setup agent edits your code locally.',
        icon: <IconSparkles />,
    },
]

const OTHER_METHODS: Choice<InstallMethod>[] = [
    {
        value: 'agent',
        title: 'Use your coding agent',
        description: 'Claude Code, Cursor or Codex installs PostHog through the PostHog MCP. Uses your AI credits.',
        icon: <IconTerminal />,
    },
    {
        value: 'manual',
        title: 'Install it yourself',
        description: 'Follow the docs for your framework.',
        icon: <IconCode />,
    },
]

function Instruction({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Text size="sm" weight="medium">
                {title}
            </Text>
            {children}
        </div>
    )
}

// shortcut: the Wizard has no option that takes an event list, so these are shown, not passed.
// Passing them needs a Wizard CLI flag and an events field on the cloud run request.
function SetupAgentEvents({ events }: { events: string[] }): JSX.Element | null {
    if (events.length === 0) {
        return null
    }
    return (
        <Text size="sm" variant="muted">
            The setup agent also adds the {events.length} events listed in the installation checklist.
        </Text>
    )
}

export function InstallStep(): JSX.Element {
    const { installMethod, focus, resolvedTarget, platforms, trackedEvents } = useValues(guidedOnboardingLogic)
    const { setInstallMethod, next, pollEvents } = useActions(guidedOnboardingLogic)
    // Polled here, not in the checklist, which mounts twice: in the sidebar and inline on narrow screens.
    useInterval(pollEvents, 5000)
    useOnMountEffect(pollEvents)
    const { currentTeam } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { wizardCommand, isCloudOrDev } = useWizardCommand()

    return (
        <StepLayout
            title="Install PostHog"
            description="Pick how. The checklist shows when your first event arrives."
            primary={
                <Button variant="primary" onClick={next} data-attr="guided-onboarding-install-continue">
                    Continue
                </Button>
            }
        >
            {currentTeam?.api_token && (
                <Instruction title="Your project token">
                    <CopyBlock
                        text={currentTeam.api_token}
                        label="project token"
                        dataAttr="guided-onboarding-project-token"
                    />
                </Instruction>
            )}
            <ChoiceList<InstallMethod>
                choices={isCloudOrDev ? [...WIZARD_METHODS, ...OTHER_METHODS] : OTHER_METHODS}
                selected={installMethod}
                onSelect={setInstallMethod}
                dataAttrPrefix="guided-onboarding-install"
            />
            <div className="flex flex-col gap-4">
                {installMethod === 'cloud' ? (
                    currentTeam && user ? (
                        <>
                            <CloudRunPanel projectId={String(currentTeam.id)} userId={user.id} />
                            <SetupAgentEvents events={trackedEvents} />
                        </>
                    ) : null
                ) : installMethod === 'wizard' ? (
                    <Instruction title="Run this in your project folder">
                        <CopyBlock
                            text={wizardCommand}
                            label="Wizard command"
                            dataAttr="guided-onboarding-wizard-command"
                        />
                        <SetupAgentEvents events={trackedEvents} />
                    </Instruction>
                ) : installMethod === 'agent' ? (
                    <>
                        <Instruction title="1. Add the PostHog MCP to your agent">
                            <CopyBlock text={MCP_INSTALL_COMMAND} label="MCP install command" />
                        </Instruction>
                        <Instruction title="2. Ask your agent to install PostHog">
                            <CopyBlock
                                text={agentInstallPrompt(focus, resolvedTarget, platforms, trackedEvents)}
                                label="prompt"
                                wrap
                            />
                        </Instruction>
                    </>
                ) : (
                    <Instruction title="Follow the installation docs for your framework">
                        <div>
                            <Button
                                variant="link"
                                render={
                                    // eslint-disable-next-line react/forbid-elements
                                    <a
                                        href="https://posthog.com/docs/getting-started/install"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                    />
                                }
                            >
                                Open the installation docs
                            </Button>
                        </div>
                        {trackedEvents.length > 0 && (
                            <>
                                <Text size="sm" variant="muted">
                                    Then capture these events where they happen, so you can measure your goal.
                                </Text>
                                <CopyBlock
                                    text={trackedEvents.map((event) => `posthog.capture('${event}')`).join('\n')}
                                    label="event capture code"
                                    wrap
                                />
                            </>
                        )}
                    </Instruction>
                )}
            </div>
            {/* The sidebar shows the checklist on wide screens. */}
            <div className="lg:hidden">
                <InstallChecklist />
            </div>
        </StepLayout>
    )
}
