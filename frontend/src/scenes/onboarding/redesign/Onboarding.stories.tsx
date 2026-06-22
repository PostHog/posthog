import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useRef } from 'react'

import { mswDecorator } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { Onboarding } from './Onboarding'
import { onboardingLogic } from './onboardingLogic'
import { installStepLogic } from './steps/installStepLogic'

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Redesign',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
    },
    decorators: [
        (Story) => (
            <div className="h-screen">
                <Story />
            </div>
        ),
        mswDecorator({
            // The redesign is cloud-first: the data-region field and wizard command both require a cloud realm.
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud', can_create_org: true },
            },
            post: {
                '/api/organizations/:organizationId/invites/delegate/': () => [200, { id: 'storybook-invite' }],
            },
        }),
    ],
}
export default meta

type Story = StoryObj

/**
 * Renders the redesign onboarding scene seeded to a specific step. Seeding runs once, before the
 * scene reads logic state, so the target screen paints without a flash through step 0.
 */
function OnboardingScreen({ seed }: { seed: () => void }): JSX.Element {
    const seeded = useRef(false)
    useMountedLogic(onboardingLogic)
    useMountedLogic(installStepLogic)
    if (!seeded.current) {
        seeded.current = true
        seed()
    }
    return <Onboarding />
}

function seedAccount(): void {
    onboardingLogic.actions.setName('Fernando Gomes')
    onboardingLogic.actions.setOrganizationName('Acme')
}

export const CreateOrganization: Story = {
    render: () => (
        <OnboardingScreen
            seed={() => {
                seedAccount()
                onboardingLogic.actions.setRole('founder')
            }}
        />
    ),
}

export const Company: Story = {
    render: () => (
        <OnboardingScreen
            seed={() => {
                seedAccount()
                onboardingLogic.actions.setCurrentStepIndex(1)
                onboardingLogic.actions.setArchetype('b2b_saas')
            }}
        />
    ),
}

export const Install: Story = {
    render: () => (
        <OnboardingScreen
            seed={() => {
                seedAccount()
                onboardingLogic.actions.setArchetype('b2b_saas')
                onboardingLogic.actions.setCurrentStepIndex(2)
            }}
        />
    ),
}

export const InstallDelegateToDeveloper: Story = {
    render: () => (
        <OnboardingScreen
            seed={() => {
                seedAccount()
                onboardingLogic.actions.setArchetype('b2b_saas')
                onboardingLogic.actions.setCurrentStepIndex(2)
                installStepLogic.actions.setDelegateOpen(true)
                installStepLogic.actions.setDelegateEmail('alex@acme.com')
            }}
        />
    ),
}

export const Configure: Story = {
    render: () => (
        <OnboardingScreen
            seed={() => {
                seedAccount()
                onboardingLogic.actions.setArchetype('b2b_saas')
                onboardingLogic.actions.setCurrentStepIndex(3)
            }}
        />
    ),
}

export const LearnUserTrack: Story = {
    render: () => (
        <OnboardingScreen
            seed={() => {
                seedAccount()
                onboardingLogic.actions.setTrack('user')
                onboardingLogic.actions.setCurrentStepIndex(2)
            }}
        />
    ),
}

export const Done: Story = {
    render: () => (
        <OnboardingScreen
            seed={() => {
                seedAccount()
                onboardingLogic.actions.setArchetype('b2b_saas')
                onboardingLogic.actions.setCurrentStepIndex(4)
            }}
        />
    ),
}
