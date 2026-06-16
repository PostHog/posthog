import type { Meta, StoryFn } from '@storybook/react'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { SignupContainer } from './SignupContainer'
import { signupLogic } from './signupForm/signupLogic'

type StoryArgs = {
    cloud: boolean
    region: 'US' | 'EU'
    googleOAuth: boolean
    github: boolean
    gitlab: boolean
    panel: 0 | 1 | 2
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Signup (paper-desk)',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: { [FEATURE_FLAGS.AUTH_FLOW_VARIANT]: 'paper-desk' },
    },
    decorators: [
        mswDecorator({
            get: { '/api/users/@me': () => [500, null] },
            post: { '/api/signup': (_, __, ctx) => [ctx.delay(1000), ctx.status(200), ctx.json({ success: true })] },
        }),
    ],
    argTypes: {
        cloud: { control: 'boolean', name: 'Cloud' },
        region: { control: 'select', options: ['US', 'EU'], name: 'Region', if: { arg: 'cloud' } },
        googleOAuth: { control: 'boolean', name: 'Google OAuth' },
        github: { control: 'boolean', name: 'GitHub' },
        gitlab: { control: 'boolean', name: 'GitLab' },
        panel: {
            control: 'select',
            name: 'Step',
            options: [0, 1, 2],
            mapping: { 0: '1 — Email', 1: '2 — Password', 2: '3 — Profile' },
        },
    },
    args: {
        cloud: true,
        region: 'US',
        googleOAuth: true,
        github: true,
        gitlab: true,
        panel: 0,
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ cloud, region, googleOAuth, github, gitlab, panel }) => {
    useStorybookMocks({
        get: {
            '/_preflight': {
                ...preflightJson,
                cloud,
                region: cloud ? region : undefined,
                realm: cloud ? 'cloud' : 'hosted-clickhouse',
                is_debug: cloud,
                can_create_org: cloud,
                available_social_auth_providers: {
                    'google-oauth2': googleOAuth,
                    github,
                    gitlab,
                    saml: false,
                },
            },
        },
    })

    useDelayedOnMountEffect(() => userLogic.actions.loadUserSuccess(null))

    useEffect(() => {
        signupLogic.actions.setPanel(panel)
        if (panel > 0) {
            signupLogic.actions.setSignupPanelEmailValue('email', 'test@posthog.com')
        }
    }, [panel])

    return <SignupContainer />
}

export const Default: StoryFn<StoryArgs> = Template.bind({})

export const SelfHosted: StoryFn<StoryArgs> = Template.bind({})
SelfHosted.args = { cloud: false, googleOAuth: false, github: false, gitlab: false }

export const PasswordStep: StoryFn<StoryArgs> = Template.bind({})
PasswordStep.args = { panel: 1 }

export const ProfileStep: StoryFn<StoryArgs> = Template.bind({})
ProfileStep.args = { panel: 2 }
