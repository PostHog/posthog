import { Meta } from '@storybook/react'

import { CyclotronJobInputs } from './CyclotronJobInputs'

const meta: Meta<typeof CyclotronJobInputs> = {
    title: 'Components/CyclotronJobInputs',
    component: CyclotronJobInputs,
}
export default meta

export const Default = (): JSX.Element => {
    return (
        <div className="max-w-160">
            <CyclotronJobInputs
                showSource={false}
                sampleGlobalsWithInputs={null}
                configuration={{
                    inputs_schema: [
                        {
                            type: 'dictionary',
                            key: 'properties',
                            label: 'Property mapping',
                            description: 'Map PostHog properties to Customer.io attributes',
                            required: false,
                        },
                    ],
                    inputs: {
                        properties: {
                            value: {
                                email: '{person.properties.email}',
                                plan: '{person.properties.plan}',
                            },
                        },
                    },
                }}
                onInputChange={() => {}}
            />
        </div>
    )
}

export const WithEmptyValue = (): JSX.Element => {
    return (
        <div className="max-w-160">
            <CyclotronJobInputs
                showSource={false}
                sampleGlobalsWithInputs={null}
                configuration={{
                    inputs_schema: [
                        {
                            type: 'dictionary',
                            key: 'properties',
                            label: 'Property mapping',
                            description: 'Map PostHog properties to Customer.io attributes',
                            required: false,
                        },
                    ],
                    inputs: {
                        properties: {
                            value: {
                                email: '{person.properties.email}',
                                name: '',
                                plan: '{person.properties.plan}',
                            },
                        },
                    },
                }}
                onInputChange={() => {}}
            />
        </div>
    )
}
