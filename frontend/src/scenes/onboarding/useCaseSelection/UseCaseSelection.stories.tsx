import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { DecoratorFunction, Parameters } from '@storybook/types'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { UserRole } from '~/types'

const createDecoratorsForRole = (role: UserRole): DecoratorFunction<any>[] => [
    mswDecorator({
        get: {
            '/api/users/@me/': () => [
                200,
                {
                    ...MOCK_DEFAULT_USER,
                    role_at_organization: role,
                },
            ],
        },
    }),
]

const createViewportParameters = (width: number, height: number): Partial<Parameters> => ({
    testOptions: {
        viewport: {
            width,
            height,
        },
    },
})

const meta: Meta = {
    component: App,
    title: 'Scenes-Other/Onboarding/Use Case Selection',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        pageUrl: urls.useCaseSelection(),
        featureFlags: [FEATURE_FLAGS.ONBOARDING_GREAT_FOR_ROLE],
        ...createViewportParameters(2048, 1024),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/billing/': { ...billingJson },
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

type Story = StoryObj<typeof meta>

export const Base: Story = {}
export const Mobile: Story = { parameters: createViewportParameters(568, 1024) }
export const Tablet: Story = { parameters: createViewportParameters(768, 1024) }

export const DataRole: Story = { decorators: createDecoratorsForRole(UserRole.Data) }
export const EngineeringRole: Story = { decorators: createDecoratorsForRole(UserRole.Engineering) }
export const FounderRole: Story = { decorators: createDecoratorsForRole(UserRole.Founder) }
export const LeadershipRole: Story = { decorators: createDecoratorsForRole(UserRole.Leadership) }
export const MarketingRole: Story = { decorators: createDecoratorsForRole(UserRole.Marketing) }
export const ProductRole: Story = { decorators: createDecoratorsForRole(UserRole.Product) }
export const SalesRole: Story = { decorators: createDecoratorsForRole(UserRole.Sales) }
