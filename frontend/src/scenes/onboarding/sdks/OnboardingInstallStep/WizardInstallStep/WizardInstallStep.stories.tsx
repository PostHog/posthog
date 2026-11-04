import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { App } from 'scenes/App'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import type { WizardRunApi } from 'products/wizard/frontend/generated/api.schemas'

import { onboardingLogic } from '../../../onboardingLogic'

const cloudRun: WizardRunApi = {
    id: '00000000-0000-4000-8000-000000000001',
    team_id: MOCK_DEFAULT_TEAM.id,
    created_by_id: MOCK_DEFAULT_USER.id,
    created_by: null,
    environment: 'cloud',
    workspace: { type: 'git_repository', repository: 'example/sample-project' },
    program: {
        id: 'posthog-integration',
        name: 'PostHog integration',
        description: 'Install PostHog',
        wizard_version: '2.67.0',
        command: [],
        tags: [],
        required_programs: [],
        supported_environments: ['local', 'cloud'],
    },
    status: 'created',
    stage: 'dispatching',
    created_at: '2023-05-25T00:00:01Z',
    updated_at: null,
    started_at: null,
    finished_at: null,
    deadline_at: null,
    error_code: null,
    error_message: null,
}

const cloudSetupMocks = mswDecorator({
    get: {
        '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud', wizard_cloud_run_available: true },
        '/api/environments/:team_id/integrations/': {
            results: [
                {
                    id: 1,
                    kind: 'github',
                    display_name: 'example',
                    config: { account: { name: 'example', type: 'Organization' } },
                    created_at: '2023-05-24T00:00:00Z',
                },
            ],
        },
        '/api/environments/:team_id/integrations/:id/github_repos/': {
            repositories: [
                {
                    id: 1,
                    name: 'sample-project',
                    full_name: 'example/sample-project',
                    archived: false,
                    private: false,
                    can_push: true,
                },
            ],
            has_more: false,
        },
        '/api/projects/:team_id/wizard/registry/': {
            count: 1,
            results: [cloudRun.program],
        },
        '/api/projects/:team_id/wizard/runs/': { count: 0, results: [], next: null },
        '/api/projects/:team_id/wizard/runs/:run_id/': cloudRun,
        '/api/projects/:team_id/wizard/runs/:run_id/tasks/': { tasks: [] },
        '/api/projects/:team_id/wizard/runs/:run_id/artifacts/': { count: 0, results: [] },
        '/api/projects/:team_id/wizard/runs/:run_id/stream/': () => [404],
    },
    post: {
        '/api/projects/:team_id/wizard/runs/': cloudRun,
    },
})

/** The onboarding install step: the full layout and the simple flow's compact layout. */

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Install Step',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
                '/stats': {},
                '/events': {},
                '/api/billing/': { ...billingJson },
            },
            patch: {
                '/api/environments/:team_id/add_product_intent/': {},
            },
            post: {
                '/api/projects/:team_id/file_system/home_folder/': {
                    id: 'home',
                    path: 'Users/Example',
                    type: 'folder',
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj

/** Lands on the install step for product analytics. */
function installStepStory({
    featureFlags = {},
    simple = false,
    cloud = false,
}: {
    featureFlags?: Record<string, string | boolean>
    simple?: boolean
    cloud?: boolean
}): Story {
    return {
        render: () => {
            useMountedLogic(onboardingLogic)
            const { setProduct } = useActions(onboardingLogic)

            useDelayedOnMountEffect(() => {
                if (simple) {
                    router.actions.push(urls.simpleOnboarding(), {
                        step: `${OnboardingStepKey.INSTALL}:${ProductKey.PRODUCT_ANALYTICS}`,
                    })
                    return
                }
                setProduct(availableOnboardingProducts[ProductKey.PRODUCT_ANALYTICS])
                router.actions.push(
                    urls.onboarding({ productKey: ProductKey.PRODUCT_ANALYTICS, stepKey: OnboardingStepKey.INSTALL })
                )
            })

            return <App />
        },
        parameters: {
            featureFlags,
            testOptions: {
                waitForSelector: cloud ? '[data-attr="wizard-cloud-run-block"]' : '[data-attr="wizard-command-block"]',
            },
        },
    }
}

/** The intro, the CLI command block, and the framework badges. */
export const ControlArm: Story = installStepStory({})

/** The simple flow's compact install step. */
export const SimpleFlow: Story = installStepStory({
    simple: true,
    featureFlags: { [FEATURE_FLAGS.ONBOARDING_SIMPLE_FLOW]: 'test' },
})

export const CloudSetup: Story = {
    ...installStepStory({ cloud: true, featureFlags: { [FEATURE_FLAGS.WIZARD_ONBOARDING_CLOUD_RUNS_ENABLED]: true } }),
    decorators: [cloudSetupMocks],
}

export const SimpleCloudSetup: Story = {
    ...installStepStory({
        simple: true,
        cloud: true,
        featureFlags: {
            [FEATURE_FLAGS.ONBOARDING_SIMPLE_FLOW]: 'test',
            [FEATURE_FLAGS.WIZARD_ONBOARDING_CLOUD_RUNS_ENABLED]: true,
        },
    }),
    decorators: [cloudSetupMocks],
}
