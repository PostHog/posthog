import { Meta, StoryObj } from '@storybook/react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { ActionStepType } from '~/types'

import { ActionStepConditions, ActionStepSummary } from './actionStepDescription'

const meta: Meta<typeof ActionStepSummary> = {
    title: 'Components/Action Step Description',
    component: ActionStepSummary,
    parameters: {
        docs: {
            description: {
                component:
                    'How a single action step is described on the actions list. `ActionStepSummary` is the one-line, scannable label shown in the Type column — autocapture steps carry their most identifying detail (text, else selector, else link) so the list is not a wall of "Autocapture". `ActionStepConditions` is the full breakdown shown in the hover tooltip.',
            },
        },
    },
    tags: ['autodocs'],
}
export default meta
type Story = StoryObj<typeof ActionStepSummary>

const VARIANTS: { label: string; step: ActionStepType }[] = [
    {
        label: 'Autocapture — text',
        step: { event: '$autocapture', text: 'Sign up', text_matching: 'exact' },
    },
    {
        label: 'Autocapture — selector only',
        step: { event: '$autocapture', selector: 'button.signup-btn' },
    },
    {
        label: 'Autocapture — link (href) only',
        step: { event: '$autocapture', href: 'https://posthog.com/pricing', href_matching: 'contains' },
    },
    {
        label: 'Autocapture — text + selector + property filter',
        step: {
            event: '$autocapture',
            text: 'Buy now',
            text_matching: 'exact',
            selector: 'div.pricing button.cta',
            properties: [{ key: '$current_url', value: '/pricing', operator: 'icontains', type: 'event' }] as any,
        },
    },
    {
        label: 'Autocapture — no identifying detail',
        step: { event: '$autocapture' },
    },
    {
        label: 'Page view — URL contains',
        step: { event: '$pageview', url: 'posthog.com/pricing', url_matching: 'contains' },
    },
    {
        label: 'Page view — URL matches regex',
        step: { event: '$pageview', url: 'posthog\\.com/blog/.*', url_matching: 'regex' },
    },
    {
        label: 'Mobile screen — screen name',
        step: {
            event: '$screen',
            properties: [{ key: '$screen_name', value: 'HomeScreen', operator: 'exact', type: 'event' }] as any,
        },
    },
    {
        label: 'Custom event',
        step: { event: 'purchase_completed' },
    },
    {
        label: 'Any event',
        step: { event: null },
    },
]

export const StepVariants: Story = {
    render: () => (
        <div className="flex flex-col gap-2 max-w-4xl">
            <div className="flex items-center gap-4 text-xs font-semibold text-secondary">
                <span className="w-64 shrink-0">Step</span>
                <span className="w-72 shrink-0">Summary (Type column)</span>
                <span>Conditions (hover tooltip)</span>
            </div>
            {VARIANTS.map(({ label, step }) => (
                <div key={label} className="flex items-start gap-4 border rounded p-2 bg-surface-primary">
                    <span className="text-xs text-secondary w-64 shrink-0">{label}</span>
                    <div className="w-72 shrink-0">
                        <ActionStepSummary step={step} />
                    </div>
                    <div className="text-xs">
                        <ActionStepConditions step={step} />
                    </div>
                </div>
            ))}
        </div>
    ),
    parameters: {
        docs: {
            description: {
                story: 'Left: the one-line summary rendered in the Type column. Right: the full condition breakdown that appears in the hover tooltip, shown inline here so it is visible without hovering.',
            },
        },
    },
}

export const SummaryWithTooltip: Story = {
    render: () => (
        <div className="flex flex-col gap-2 max-w-2xl">
            <span className="text-xs text-secondary">Hover a row to see the full conditions tooltip.</span>
            {VARIANTS.map(({ label, step }) => (
                <Tooltip key={label} title={<ActionStepConditions step={step} />} placement="right">
                    <div className="w-fit border rounded p-2 bg-surface-primary">
                        <ActionStepSummary step={step} />
                    </div>
                </Tooltip>
            ))}
        </div>
    ),
    parameters: {
        docs: {
            description: {
                story: 'The exact interaction used on the actions list: the summary is the trigger, hovering reveals the conditions breakdown.',
            },
        },
    },
}
