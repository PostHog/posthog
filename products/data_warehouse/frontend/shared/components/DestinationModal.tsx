import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    DestinationModalLogicProps,
    destinationModalLogic,
} from 'products/data_warehouse/frontend/shared/logics/destinationModalLogic'

import { DestinationIcon } from './DestinationIcon'

export function DestinationModal(props: DestinationModalLogicProps): JSX.Element {
    const logic = destinationModalLogic(props)
    const { isOpen, editing, editingIntegration, isDestinationFormSubmitting } = useValues(logic)
    const { closeModal, submitDestinationForm } = useActions(logic)

    return (
        <>
            <LemonModal
                isOpen={isOpen}
                onClose={closeModal}
                title={
                    <div className="flex gap-2 items-center">
                        <DestinationIcon type="Postgres" />
                        <span>{editing ? 'Edit destination' : 'New destination'}</span>
                    </div>
                }
                footer={
                    <>
                        <LemonButton type="secondary" onClick={closeModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={submitDestinationForm}
                            loading={isDestinationFormSubmitting}
                            data-attr="warehouse-destination-save"
                        >
                            {editing ? 'Save' : 'Add destination'}
                        </LemonButton>
                    </>
                }
            >
                <Form
                    logic={destinationModalLogic}
                    props={props}
                    formKey="destinationForm"
                    className="deprecated-space-y-4"
                >
                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="Customer Postgres" data-attr="warehouse-destination-name" />
                    </LemonField>

                    <LemonField
                        name="integrationId"
                        label="Connection"
                        info="Credentials live on the connection, so one connection can back several destinations and batch exports."
                    >
                        {({ value, onChange }) =>
                            editing ? (
                                editingIntegration ? (
                                    <IntegrationView integration={editingIntegration} suffix={<></>} />
                                ) : (
                                    <span className="text-muted">
                                        This destination's connection is no longer available.
                                    </span>
                                )
                            ) : (
                                <IntegrationChoice
                                    integration="postgresql"
                                    value={value ?? undefined}
                                    onChange={onChange}
                                />
                            )
                        }
                    </LemonField>

                    <div className="flex gap-2">
                        <LemonField name="database" label="Database" className="flex-1">
                            <LemonInput data-attr="warehouse-destination-database" disabled={!!editing} />
                        </LemonField>
                        <LemonField name="schema" label="Schema" className="flex-1">
                            <LemonInput data-attr="warehouse-destination-schema" disabled={!!editing} />
                        </LemonField>
                    </div>

                    {editing ? (
                        <LemonBanner type="info">
                            The connection, database and schema are fixed once a destination exists. Everything already
                            synced sits where it is now, so pointing this somewhere else would leave that behind and
                            need a full resync. Add a second destination instead.
                        </LemonBanner>
                    ) : null}
                </Form>
            </LemonModal>
        </>
    )
}
