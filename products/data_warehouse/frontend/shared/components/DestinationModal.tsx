import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { CREATABLE_DESTINATION_TYPES } from 'products/data_warehouse/frontend/shared/destinations/destinationDefinitions'
import {
    DestinationModalLogicProps,
    destinationModalLogic,
} from 'products/data_warehouse/frontend/shared/logics/destinationModalLogic'

import { DestinationIcon, destinationTypeLabel } from './DestinationIcon'

export function DestinationModal(props: DestinationModalLogicProps): JSX.Element {
    const logic = destinationModalLogic(props)
    const { isOpen, editing, editingIntegration, isDestinationFormSubmitting, destinationForm, definition } =
        useValues(logic)
    const { closeModal, submitDestinationForm, deleteDestination, setDestinationType, setIntegrationKind } =
        useActions(logic)

    const Fields = definition.Fields

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title={
                <div className="flex gap-2 items-center">
                    <DestinationIcon type={destinationForm.type} />
                    <span>{editing ? 'Edit destination' : 'New destination'}</span>
                </div>
            }
            footer={
                <>
                    {editing && !editing.is_posthog_warehouse ? (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() => deleteDestination(editing)}
                            data-attr="warehouse-destination-delete"
                            // Sits apart from Cancel and Save so it is not reached by accident.
                            className="mr-auto"
                        >
                            Delete
                        </LemonButton>
                    ) : null}
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
                {!editing && (
                    <LemonField name="type" label="Type">
                        {({ value }) => (
                            <LemonSelect
                                value={value}
                                onChange={setDestinationType}
                                data-attr="warehouse-destination-type"
                                options={CREATABLE_DESTINATION_TYPES.map((type) => ({
                                    value: type,
                                    label: destinationTypeLabel(type),
                                    icon: <DestinationIcon type={type} />,
                                }))}
                            />
                        )}
                    </LemonField>
                )}

                <LemonField name="name" label="Name">
                    <LemonInput
                        placeholder={`My ${destinationTypeLabel(destinationForm.type)}`}
                        data-attr="warehouse-destination-name"
                    />
                </LemonField>

                {/* A type backed by more than one integration kind needs the provider picked
                    first, because the connection list is per kind. */}
                {!editing && definition.integrationKinds.length > 1 && (
                    <LemonField name="integrationKind" label="Provider">
                        {({ value }) => (
                            <LemonSelect
                                value={value}
                                onChange={setIntegrationKind}
                                data-attr="warehouse-destination-provider"
                                options={definition.integrationKinds.map((kind) => ({
                                    value: kind,
                                    label: getIntegrationNameFromKind(kind),
                                }))}
                            />
                        )}
                    </LemonField>
                )}

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
                                integration={destinationForm.integrationKind}
                                value={value ?? undefined}
                                onChange={onChange}
                            />
                        )
                    }
                </LemonField>

                <Fields isNew={!editing} formValues={destinationForm} selectedIntegration={editingIntegration} />

                {editing ? (
                    <LemonBanner type="info">
                        The connection and the place this writes to are fixed once a destination exists. Everything
                        already synced sits where it is now, so pointing this somewhere else would leave that behind and
                        need a full resync. Add a second destination instead.
                    </LemonBanner>
                ) : null}
            </Form>
        </LemonModal>
    )
}
