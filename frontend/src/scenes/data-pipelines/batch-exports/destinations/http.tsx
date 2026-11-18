import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { DestinationDefinition } from './types'

export const httpDefinition: DestinationDefinition = {
    type: 'HTTP',
    defaults: () => ({}),
    requiredFields: () => ['url', 'token'],
    eventTableExtraFields: {
        elements_chain: {
            name: 'elements_chain',
            hogql_value: 'elements_chain',
            type: 'string',
            schema_valid: true,
        },
    },
    eventTableOverrides: { includeGenericPersonFields: false },
    Fields: function HttpFields() {
        return (
            <>
                <LemonField name="url" label="PostHog region">
                    <LemonSelect
                        options={[
                            { value: 'https://us.i.posthog.com/batch/', label: 'US' },
                            { value: 'https://eu.i.posthog.com/batch/', label: 'EU' },
                        ]}
                    />
                </LemonField>
                <LemonField name="token" label="Destination project token">
                    <LemonInput placeholder="e.g. phc_12345..." />
                </LemonField>
            </>
        )
    },
}
