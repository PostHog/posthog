import type { Meta, StoryFn } from '@storybook/react'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { VerifyEmail } from './VerifyEmail'
import { verifyEmailLogic } from './verifyEmailLogic'

type VerifyEmailView = 'pending' | 'success' | 'invalid'

type StoryArgs = {
    view: VerifyEmailView
}

const meta: Meta<StoryArgs> = {
    title: 'Scenes-Other/Verify Email',
    tags: ['test-skip'],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    argTypes: {
        view: {
            control: 'select',
            name: 'View',
            options: ['pending', 'success', 'invalid'] satisfies VerifyEmailView[],
        },
    },
    args: {
        view: 'pending',
    },
}
export default meta

const Template: StoryFn<StoryArgs> = ({ view }) => {
    useStorybookMocks({
        get: {
            '/_preflight': { ...preflightJson },
            '/api/users/@me': () => [200, { email: 'test@posthog.com', first_name: 'Test' }],
        },
    })

    useEffect(() => {
        verifyEmailLogic.actions.setView(view)
        verifyEmailLogic.actions.setUuid('12345678')
    }, [view])

    return <VerifyEmail />
}

export const Default: StoryFn<StoryArgs> = Template.bind({})

export const Pending: StoryFn<StoryArgs> = Template.bind({})
Pending.args = { view: 'pending' }

export const Success: StoryFn<StoryArgs> = Template.bind({})
Success.args = { view: 'success' }

export const Invalid: StoryFn<StoryArgs> = Template.bind({})
Invalid.args = { view: 'invalid' }
