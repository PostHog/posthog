import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { Progress, ProgressLabel, ProgressValue, Text, ToastProvider, cn } from '@posthog/quill'

import type { WorkStepApi } from 'products/today/frontend/generated/api.schemas'

import { checkoutWorkThread, finishedWorkThread } from './workThreadFixtures'
import { WorkThreadView } from './WorkThreadView'

function SampleRollout({ label, value, note }: { label: string; value: number; note: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <Progress value={value}>
                <ProgressLabel>{label}</ProgressLabel>
                <ProgressValue />
            </Progress>
            <Text size="xs" variant="muted" className="m-0">
                {note}
            </Text>
        </div>
    )
}

function renderSampleEvidence(step: WorkStepApi): JSX.Element | null {
    switch (step.item?.type) {
        case 'experiment':
            return (
                <div className="flex flex-col gap-2">
                    <Progress value={41}>
                        <ProgressLabel>Control</ProgressLabel>
                        <ProgressValue>{() => '4.1%'}</ProgressValue>
                    </Progress>
                    <Progress value={48} variant="success">
                        <ProgressLabel>One-page</ProgressLabel>
                        <ProgressValue>{() => '4.8%'}</ProgressValue>
                    </Progress>
                </div>
            )
        case 'feature_flag':
            return step.key === 'flag-created' ? (
                <SampleRollout label="Rollout" value={0} note="Nobody sees the new checkout yet" />
            ) : (
                <SampleRollout label="Rollout" value={100} note="Everyone, for 34 days" />
            )
        default:
            return null
    }
}

const withWidth: Decorator = (Story, context) => (
    <ToastProvider>
        <div className={cn(context.parameters.narrow ? 'w-105' : 'w-200')}>
            <Story />
        </div>
    </ToastProvider>
)

const meta: Meta<typeof WorkThreadView> = {
    title: 'Layout/Today/Work thread',
    component: WorkThreadView,
    decorators: [withWidth],
    args: {
        thread: checkoutWorkThread,
        renderEvidence: renderSampleEvidence,
        onRunAction: () => {},
    },
    parameters: {
        layout: 'padded',
        testOptions: { waitForSelector: '[data-attr="work-thread"]' },
    },
}
export default meta

type Story = StoryObj<typeof WorkThreadView>

export const Checkout: Story = {}

export const HelperOpen: Story = {
    parameters: { testOptions: { waitForSelector: '[data-attr="work-thread-helper"]' } },
    play: async () => {
        const page = within(document.body)
        await userEvent.click(await page.findByRole('button', { name: 'Ship the winner…' }))
        await page.findByRole('button', { name: 'Ship variant' })
    },
}

export const PromptOpen: Story = {
    parameters: { testOptions: { waitForSelector: '[data-attr="work-thread-prompt"]' } },
    play: async (context) => {
        await HelperOpen.play?.(context)
        const page = within(document.body)
        await userEvent.click(await page.findByRole('button', { name: 'Copy prompt…' }))
        await page.findByLabelText('Prompt for your own agent')
    },
}

export const ItemDrawerOpen: Story = {
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForSelector: '[data-attr="work-thread-item-drawer-open"]' },
    },
    play: async () => {
        const page = within(document.body)
        await userEvent.click(await page.findByRole('button', { name: 'View experiment' }))
        await page.findByRole('link', { name: 'Open in Experiments' })
    },
}

/** Both steps are about the same flag, so the drawer must show the facts of the step it was opened from. */
export const ItemDrawerOpenFromEarlierStep: Story = {
    args: { thread: finishedWorkThread },
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForSelector: '[data-attr="work-thread-item-drawer-open"]' },
    },
    play: async () => {
        const page = within(document.body)
        const [firstToggle] = await page.findAllByRole('button', { name: 'Expand step' })
        await userEvent.click(firstToggle)
        await userEvent.click(await page.findByRole('button', { name: 'View flag' }))
        const drawer = within(await page.findByRole('dialog'))
        await drawer.findByText('100% for 34 days')
    },
}

export const Finished: Story = {
    args: { thread: finishedWorkThread },
}

export const NarrowContainer: Story = {
    parameters: { narrow: true },
}
