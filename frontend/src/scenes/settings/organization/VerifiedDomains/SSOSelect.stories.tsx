import { useState } from 'react'
import { StoryFn, Meta } from '@storybook/react'
import { SSOSelect } from './SSOSelect'
import { SSOProvider } from '~/types'
import { useStorybookMocks } from '~/mocks/browser'
import preflightJSON from '~/mocks/fixtures/_preflight.json'

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
        <div style={{ maxWidth: 600 }}>
            <SSOSelect {...args} value={value} onChange={(val) => setValue(val)} />
        </div>
    )
}

export const SSOSelect_ = Template.bind({})

SSOSelect_.args = {
    loading: false,
    samlAvailable: true,
}
