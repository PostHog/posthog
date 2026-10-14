import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { WarehouseDestinationDefinition } from './types'

export const bigqueryDefinition: WarehouseDestinationDefinition = {
    type: 'BigQuery',
    integrationKinds: ['google-cloud-service-account'],
    defaults: () => ({}),
    // Project is optional: the writer falls back to the service account's own project.
    requiredFields: () => ['dataset'],
    configKeys: ['dataset', 'project'],
    retargetingKeys: ['dataset', 'project'],
    Fields: function BigQueryFields({ isNew }) {
        return (
            <div className="flex gap-2">
                <LemonField name="dataset" label="Dataset" className="flex-1">
                    <LemonInput placeholder="my_dataset" disabled={!isNew} data-attr="warehouse-destination-dataset" />
                </LemonField>
                <LemonField
                    name="project"
                    label="Project"
                    className="flex-1"
                    showOptional
                    info="Leave empty to use the project the service account belongs to."
                >
                    <LemonInput
                        placeholder="The service account's project"
                        disabled={!isNew}
                        data-attr="warehouse-destination-project"
                    />
                </LemonField>
            </div>
        )
    },
}
