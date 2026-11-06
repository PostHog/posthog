import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { IntegrationType } from '~/types'

import type { WarehouseDestinationDefinition } from './types'

/**
 * A username and password connection stores the cluster's host. An IAM role or access key
 * connection stores only the AWS identity, so the destination has to name the cluster.
 */
function needsClusterEndpoint(integration: IntegrationType | null | undefined): boolean {
    return !!integration && !integration.config?.host
}

// Redshift speaks the Postgres wire protocol and its writer subclasses the Postgres one, so it
// takes the same database and schema. Kept as its own definition rather than sharing Postgres's,
// because the two pick credentials from different integration kinds.
export const redshiftDefinition: WarehouseDestinationDefinition = {
    type: 'Redshift',
    integrationKinds: ['aws-redshift'],
    defaults: () => ({ database: 'dev', schema: 'public' }),
    requiredFields: ({ selectedIntegration }) =>
        needsClusterEndpoint(selectedIntegration) ? ['host', 'database', 'schema'] : ['database', 'schema'],
    configKeys: ['host', 'port', 'database', 'schema'],
    retargetingKeys: ['host', 'database', 'schema'],
    Fields: function RedshiftFields({ isNew, selectedIntegration }) {
        return (
            <>
                {needsClusterEndpoint(selectedIntegration) ? (
                    <div className="flex flex-wrap gap-2">
                        <LemonField
                            name="host"
                            label="Host"
                            className="flex-1 min-w-60"
                            info="The cluster or workgroup endpoint. This connection signs in with AWS, so it has no host of its own."
                        >
                            <LemonInput
                                placeholder="my-cluster.abc123.us-east-1.redshift.amazonaws.com"
                                disabled={!isNew}
                                data-attr="warehouse-destination-host"
                            />
                        </LemonField>
                        <LemonField name="port" label="Port" showOptional className="w-28">
                            <LemonInput type="number" placeholder="5439" data-attr="warehouse-destination-port" />
                        </LemonField>
                    </div>
                ) : null}
                <div className="flex flex-wrap gap-2">
                    <LemonField name="database" label="Database" className="flex-1 min-w-40">
                        <LemonInput placeholder="dev" disabled={!isNew} data-attr="warehouse-destination-database" />
                    </LemonField>
                    <LemonField name="schema" label="Schema" className="flex-1 min-w-40">
                        <LemonInput placeholder="public" disabled={!isNew} data-attr="warehouse-destination-schema" />
                    </LemonField>
                </div>
            </>
        )
    },
}
