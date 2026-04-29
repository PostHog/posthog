import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { InspectorListItemDoctor } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { mswDecorator } from '~/mocks/browser'

import { ItemDoctor, ItemDoctorDetail, ItemDoctorProps } from './ItemDoctor'

type Story = StoryObj<typeof ItemDoctor>
const meta: Meta<typeof ItemDoctor> = {
    title: 'Components/PlayerInspector/ItemDoctor',
    component: ItemDoctor,
    decorators: [
        mswDecorator({
            get: {},
        }),
    ],
}
export default meta

const makeDoctorItem = (
    tag: string,
    data?: Record<string, any>,
    highlightColor?: 'danger' | 'warning' | 'primary'
): InspectorListItemDoctor => ({
    timestamp: dayjs('2024-06-15T10:30:00Z'),
    timeInRecording: 45000,
    search: tag,
    type: 'doctor',
    tag,
    data,
    highlightColor,
    key: `doctor-${tag}`,
})

const BasicTemplate: StoryFn<typeof ItemDoctor> = (props: Partial<ItemDoctorProps>) => {
    const propsToUse = props as ItemDoctorProps

    return (
        <div className="flex flex-col gap-2 min-w-96">
            <h3>Collapsed</h3>
            <ItemDoctor {...propsToUse} />
            <LemonDivider />
            <h3>Expanded</h3>
            <ItemDoctorDetail {...propsToUse} />
        </div>
    )
}

export const AssetErrorsWithCSPViolations: Story = BasicTemplate.bind({})
AssetErrorsWithCSPViolations.args = {
    item: makeDoctorItem(
        'asset errors (247 total)',
        {
            'CSP violations (198)': {
                'img-src': 87,
                'font-src': 42,
                'style-src-elem': 38,
                'script-src': 31,
            },
            'stylesheet errors (24)':
                'cdn.example.com/styles/main.css, cdn.example.com/styles/vendor.css, cdn.example.com/styles/fonts.css + 5 more',
            'img errors (18)':
                'cdn.example.com/images/logo.png, cdn.example.com/images/hero.jpg, cdn.example.com/images/banner.png + 4 more',
            'font errors (7)':
                'cdn.example.com/fonts/regular.woff2, cdn.example.com/fonts/bold.woff2, cdn.example.com/fonts/icons.woff2 + 1 more',
        },
        'warning'
    ),
}

export const AssetErrorsSmall: Story = BasicTemplate.bind({})
AssetErrorsSmall.args = {
    item: makeDoctorItem(
        'asset errors (3 total)',
        {
            'img errors (2)': 'cdn.example.com/images/avatar.png, cdn.example.com/images/background.jpg',
            'stylesheet errors (1)': 'cdn.example.com/styles/theme.css',
        },
        'warning'
    ),
}

export const RrwebWarnings: Story = BasicTemplate.bind({})
RrwebWarnings.args = {
    item: makeDoctorItem(
        'rrweb warnings (156)',
        {
            'Mutation target not found': 89,
            'Unknown tag: web-component': 34,
            'Failed to apply style rule': 22,
            'Node not in document': 11,
        },
        'warning'
    ),
}

export const RrwebWarningsCountOnly: Story = BasicTemplate.bind({})
RrwebWarningsCountOnly.args = {
    item: makeDoctorItem('rrweb warnings (42)', { total: 42 }, 'warning'),
}

export const FullSnapshotEvent: Story = BasicTemplate.bind({})
FullSnapshotEvent.args = {
    item: makeDoctorItem('full snapshot event', { snapshotSize: '2.5MB' }),
}

export const SnapshotTypeCounts: Story = BasicTemplate.bind({})
SnapshotTypeCounts.args = {
    item: makeDoctorItem('count of snapshot types by window', {
        1: { incremental: 1247, full: 3, meta: 2, custom: 18, plugin: 892 },
        2: { incremental: 45, full: 1, meta: 1, custom: 2, plugin: 31 },
    }),
}

export const PosthogConfig: Story = BasicTemplate.bind({})
PosthogConfig.args = {
    item: makeDoctorItem('posthog config', {
        api_host: 'https://us.posthog.com',
        capture_pageview: true,
        capture_pageleave: true,
        session_recording: {
            recordCrossOriginIframes: true,
            maskAllInputs: false,
            maskTextSelector: '[data-sensitive]',
        },
        autocapture: true,
        persistence: 'localStorage+cookie',
    }),
}

export const SessionOptions: Story = BasicTemplate.bind({})
SessionOptions.args = {
    item: makeDoctorItem('session options', {
        sessionRecordingOptions: {
            blockClass: 'ph-no-capture',
            maskAllInputs: false,
            maskTextSelector: null,
            recordCanvas: false,
            recordCrossOriginIframes: true,
        },
        activePlugins: ['rrweb/console@1', 'rrweb/network@1'],
    }),
}

export const CustomEvent: Story = BasicTemplate.bind({})
CustomEvent.args = {
    item: makeDoctorItem('session idle', { idleDuration: 30000, reason: 'no user interaction' }),
}
