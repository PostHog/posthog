import { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { Region } from '~/types'

import { LLMProviderResidencyNotice } from './LLMProviderResidencyNotice'

const meta: Meta<typeof LLMProviderResidencyNotice> = {
    title: 'Products/AI observability/LLM provider residency notice',
    component: LLMProviderResidencyNotice,
    render: (props) => {
        useStorybookMocks({
            get: {
                '/_preflight': { ...preflightJson, cloud: true, region: Region.EU },
            },
        })

        return (
            <div className="max-w-120">
                <LLMProviderResidencyNotice {...props} />
            </div>
        )
    },
}
export default meta

type Story = StoryObj<typeof LLMProviderResidencyNotice>

export const GlobalEndpointProvider: Story = { args: { provider: 'gemini' } }
