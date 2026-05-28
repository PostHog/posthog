import type { Meta, StoryObj } from '@storybook/react'
import { weeklyDigestDraftRevision } from '../fixtures'
import { JsonView } from './JsonView'

const meta: Meta<typeof JsonView> = {
    title: 'Agent Chat/JsonView',
    component: JsonView,
    parameters: {
        layout: 'centered',
    },
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof JsonView>

export const ShallowObject: Story = {
    args: {
        value: {
            model: 'anthropic/claude-sonnet-4-6',
            temperature: 0.4,
            max_turns: 30,
            streaming: true,
            note: null,
        },
    },
}

export const NestedSpec: Story = {
    args: {
        value: weeklyDigestDraftRevision.spec,
        expandToLevel: 2,
    },
}

export const QueryResult: Story = {
    args: {
        value: {
            ok: true,
            body: [
                ['$pageview', 18420],
                ['$autocapture', 9112],
                ['agent_session_started', 312],
            ],
        },
    },
}

export const ErrorResult: Story = {
    args: {
        value: { ok: false, error: 'Upstream model rate-limited. Retry in 15s.' },
    },
}

export const Empty: Story = {
    args: {
        value: {},
    },
}

export const StartingInJsonMode: Story = {
    args: {
        value: weeklyDigestDraftRevision.spec,
        defaultView: 'json',
    },
}

export const StartingInYamlMode: Story = {
    args: {
        value: weeklyDigestDraftRevision.spec,
        defaultView: 'yaml',
    },
}

export const DeepArray: Story = {
    args: {
        value: {
            files: Array.from({ length: 5 }, (_, i) => ({
                path: `skills/skill-${i + 1}.md`,
                size: 800 + i * 120,
                meta: { ext: 'md', updated_at: '2026-05-28T11:00:00Z' },
            })),
        },
        expandToLevel: 1,
    },
}
