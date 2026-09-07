import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import { NotebookType } from '../types'
import notebook12345Json from './__mocks__/notebook-12345.json'
import { NotebookKernelInfo } from './NotebookKernelInfo'
import { notebookLogic } from './notebookLogic'

const SHORT_ID = '12345'

const COMPUTE_OPTIONS = {
    currency: 'USD',
    cpu_rate_per_core_hour: 0.2,
    memory_rate_per_gb_hour: 0.025,
    default_preset_key: 'small',
    presets: [
        {
            key: 'small',
            name: 'Small',
            description: 'Exploring data and working with small dataframes.',
            cpu_cores: 1,
            memory_gb: 2,
            hourly_price: 0.25,
        },
        {
            key: 'balanced',
            name: 'Balanced',
            description: 'Most analysis work.',
            cpu_cores: 4,
            memory_gb: 8,
            hourly_price: 1,
        },
        {
            key: 'large',
            name: 'Large',
            description: 'Large joins and cells that run for a while.',
            cpu_cores: 8,
            memory_gb: 16,
            hourly_price: 2,
        },
        {
            key: 'high_memory',
            name: 'High memory',
            description: 'Dataframes that run out of memory on the other presets.',
            cpu_cores: 8,
            memory_gb: 32,
            hourly_price: 2.4,
        },
    ],
    allowed_cpu_cores: [0.125, 0.25, 0.5, 1, 2, 4, 6, 8, 16, 32, 64],
    allowed_memory_gb: [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256],
    allowed_idle_timeout_seconds: [600, 1800, 3600, 10800, 21600, 43200],
}

const kernelStatus = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
    backend: 'modal',
    status: 'running',
    frames: [],
    cpu_cores: 1,
    memory_gb: 2,
    disk_size_gb: 10,
    idle_timeout_seconds: 3600,
    hourly_price: 0.25,
    preset_key: 'small',
    ...overrides,
})

const meta: Meta<typeof NotebookKernelInfo> = {
    title: 'Scenes-App/Notebooks/Kernel info',
    component: NotebookKernelInfo,
    // The widget lives in the notebook's right column, so pin the story to that column's width.
    // Its price column is the piece most at risk of wrapping when a preset name grows.
    decorators: [
        (Story) => (
            <BindLogic
                logic={notebookLogic}
                props={{ shortId: SHORT_ID, cachedNotebook: notebook12345Json as unknown as NotebookType }}
            >
                <div className="w-[20rem]">
                    <Story />
                </div>
            </BindLogic>
        ),
    ],
    parameters: {
        layout: 'padded',
        testOptions: { snapshotTargetSelector: '.NotebookColumn__widget' },
    },
}
export default meta

type Story = StoryObj<typeof NotebookKernelInfo>

export const RunningOnAPreset: Story = {
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/notebooks/${SHORT_ID}/kernel/status`]: kernelStatus(),
                '/api/projects/:team_id/notebooks/kernel/compute_options': COMPUTE_OPTIONS,
            },
        }),
    ],
}

export const TunedByHand: Story = {
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/notebooks/${SHORT_ID}/kernel/status`]: kernelStatus({
                    cpu_cores: 6,
                    memory_gb: 32,
                    hourly_price: 2,
                    preset_key: null,
                }),
                '/api/projects/:team_id/notebooks/kernel/compute_options': COMPUTE_OPTIONS,
            },
        }),
    ],
}

export const StoppedOnDocker: Story = {
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/notebooks/${SHORT_ID}/kernel/status`]: kernelStatus({
                    backend: 'docker',
                    status: 'stopped',
                }),
                '/api/projects/:team_id/notebooks/kernel/compute_options': COMPUTE_OPTIONS,
            },
        }),
    ],
}
