import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivationTaskStatus, TeamType } from '~/types'

import { ProductSetupPopover } from './ProductSetupPopover'
import { SetupTaskId } from './types'

interface StoryProps {
    onboardingTasks: TeamType['onboarding_tasks']
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>

const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Components/ProductSetup/ProductSetupPopover',
    parameters: {
        layout: 'centered',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/@current/': {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    created_at: new Date().toISOString(),
                },
            },
            patch: {
                '/api/environments/@current/': {},
            },
        }),
    ],
}
export default meta

const PopoverWrapper = ({ onboardingTasks }: { onboardingTasks: TeamType['onboarding_tasks'] }): JSX.Element => {
    const [visible, setVisible] = useState(true)
    const [product, setProduct] = useState(ProductKey.PRODUCT_ANALYTICS)

    useStorybookMocks({
        get: {
            '/api/environments/@current/': {
                ...MOCK_DEFAULT_TEAM,
                onboarding_tasks: onboardingTasks,
            },
        },
    })

    return (
        <div className="p-4 min-h-80">
            <ProductSetupPopover
                visible={visible}
                onClickOutside={() => setVisible(false)}
                selectedProduct={product}
                onSelectProduct={setProduct}
            >
                <LemonButton type="primary" onClick={() => setVisible(!visible)}>
                    Quick start
                </LemonButton>
            </ProductSetupPopover>
        </div>
    )
}

const Template: StoryFn<StoryProps> = ({ onboardingTasks }) => {
    return <PopoverWrapper onboardingTasks={onboardingTasks} />
}

export const Default: Story = Template.bind({})
Default.args = {
    onboardingTasks: {},
}
Default.parameters = {
    testOptions: { waitForSelector: '[role="dialog"]' },
}

export const MixedStates: Story = Template.bind({})
MixedStates.args = {
    onboardingTasks: {
        [SetupTaskId.IngestFirstEvent]: ActivationTaskStatus.COMPLETED,
        [SetupTaskId.SetUpReverseProxy]: ActivationTaskStatus.SKIPPED,
        [SetupTaskId.CreateFirstInsight]: ActivationTaskStatus.COMPLETED,
        [SetupTaskId.CreateFunnel]: ActivationTaskStatus.SKIPPED,
    },
}
MixedStates.parameters = {
    testOptions: { waitForSelector: '[role="dialog"]' },
}

export const AllTasksCompleted: Story = Template.bind({})
AllTasksCompleted.args = {
    onboardingTasks: {
        [SetupTaskId.IngestFirstEvent]: ActivationTaskStatus.COMPLETED,
        [SetupTaskId.SetUpReverseProxy]: ActivationTaskStatus.COMPLETED,
        [SetupTaskId.CreateFirstInsight]: ActivationTaskStatus.COMPLETED,
        [SetupTaskId.CreateFunnel]: ActivationTaskStatus.COMPLETED,
        [SetupTaskId.CreateFirstDashboard]: ActivationTaskStatus.COMPLETED,
        [SetupTaskId.TrackCustomEvents]: ActivationTaskStatus.COMPLETED,
        [SetupTaskId.DefineActions]: ActivationTaskStatus.COMPLETED,
        [SetupTaskId.SetUpCohorts]: ActivationTaskStatus.COMPLETED,
    },
}
AllTasksCompleted.parameters = {
    testOptions: { waitForSelector: '[role="dialog"]' },
}
