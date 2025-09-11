import { Meta, StoryFn } from '@storybook/react'
import { useState } from 'react'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJSON from '~/mocks/fixtures/_preflight.json'
import { SSOProvider } from '~/types'

import { SSOSelect } from './SSOSelect'

const meta: Meta<typeof SSOSelect> = {
    title: 'Components/SSO Select',
    component: SSOSelect,
}
export default meta

const Template: StoryFn<typeof SSOSelect> = (args) => {
    const [value, setValue] = useState('google-oauth2' as SSOProvider | '')
    useStorybookMocks({
        get: {
            '/_preflight': (_, __, ctx) => [
                ctx.delay(10),
                ctx.status(200),
                ctx.json({
                    ...preflightJSON,
                    available_social_auth_providers: {
                        github: true,
                        gitlab: false,
                        'google-oauth2': true,
                    },
                }),
            ],
        },
    })
    return (
        <div className="max-h-140">
            <SSOSelect {...args} value={value} onChange={(val) => setValue(val)} />
        </div>
    )
}

export const SSOSelect_ = Template.bind({})

SSOSelect_.args = {
    loading: false,
    samlAvailable: true,
}
