import React, { useState } from 'react'
import { ComponentStory, ComponentMeta } from '@storybook/react'
import { SSOSelect } from './SSOSelect'
import { SSOProviders } from '~/types'
import { useStorybookMocks } from '~/mocks/browser'
import preflightJSON from '~/mocks/fixtures/_preflight.json'

export default {
    title: 'Components/SSO Select',
    component: SSOSelect,
} as ComponentMeta<typeof SSOSelect>

const Template: ComponentStory<typeof SSOSelect> = (args) => {
    const [value, setValue] = useState('google-oauth2' as SSOProviders | '')
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
