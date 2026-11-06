import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { MCP_INSTALL_COMMAND } from 'lib/components/MCPHint/constants'

import { CopyBlock } from '../components/CopyBlock'
import { StepLayout } from '../components/StepLayout'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'

const MCP_INTRO: Record<string, string> = {
    wizard: "If you added the MCP when the setup agent asked at the end of its run, you're set. If you skipped it, run this in a terminal.",
    agent: 'You added the MCP in the install step. If you use more than one coding agent, run this to add it to the others.',
}

export function McpStep(): JSX.Element {
    const { installMethod, focus } = useValues(guidedOnboardingLogic)
    const { next } = useActions(guidedOnboardingLogic)

    return (
        <StepLayout
            title="Ask about your data from your coding agent"
            description="The PostHog MCP lets Claude Code, Cursor and other coding agents query your PostHog data and change your setup."
            primary={
                <Button variant="primary" onClick={next} data-attr="guided-onboarding-mcp-continue">
                    Continue
                </Button>
            }
        >
            <div className="flex flex-col gap-2">
                <Text size="sm" weight="medium">
                    Add the PostHog MCP
                </Text>
                <Text size="sm" variant="muted">
                    {MCP_INTRO[installMethod] ??
                        'Run this in a terminal. Wizard finds the coding agents on your machine, such as Claude Code, Cursor, VS Code, Windsurf and Zed, and adds the PostHog MCP to the ones you pick.'}
                </Text>
                <CopyBlock
                    text={MCP_INSTALL_COMMAND}
                    label="MCP install command"
                    dataAttr="guided-onboarding-mcp-command"
                />
            </div>
            <div className="flex flex-col gap-2">
                <Text size="sm" weight="medium">
                    Try a first question
                </Text>
                <Text size="sm" variant="muted">
                    Restart your agent, then ask it something like this.
                </Text>
                <CopyBlock
                    label="prompt"
                    wrap
                    text={
                        focus?.custom
                            ? `What does my PostHog data say about this goal: ${focus.metric}?`
                            : focus
                              ? `How did ${focus.metric} change this week, and what is driving it?`
                              : 'What are the most common events in my PostHog project this week?'
                    }
                />
            </div>
        </StepLayout>
    )
}
