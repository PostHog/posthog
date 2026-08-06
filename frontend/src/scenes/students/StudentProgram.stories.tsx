import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { billingUnsubscribedJson } from '~/mocks/fixtures/_billing_unsubscribed'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { StartupProgramLabel } from '~/types'

import { StudentProgram } from './StudentProgram'

const meta: Meta = {
    title: 'Scenes-Other/Student program',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.STUDENT_PROGRAM_INTENT],
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const FormEmpty: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                },
            },
        })

        return <StudentProgram />
    },
}

export const NoActiveSubscription: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingUnsubscribedJson,
                },
            },
        })

        return <StudentProgram />
    },
}

export const AlreadyOnProgram: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                    startup_program_label: StartupProgramLabel.Startup,
                },
            },
        })

        return <StudentProgram />
    },
}

export const PreviouslyOnProgram: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                    startup_program_label_previous: StartupProgramLabel.Startup,
                },
            },
        })

        return <StudentProgram />
    },
}

export const AnnualPlanCustomer: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                    is_annual_plan_customer: true,
                },
            },
        })

        return <StudentProgram />
    },
}

export const FlagOff: Story = {
    // Per-story parameters replace the meta's, so this drops STUDENT_PROGRAM_INTENT and renders NotFound
    parameters: {
        featureFlags: [],
    },
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                },
            },
        })

        return <StudentProgram />
    },
}
