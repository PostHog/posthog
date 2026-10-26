import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { SSFDirectionEnumApi } from '~/generated/core/api.schemas'

import { SSFSettingsLogicProps, ssfSettingsLogic } from './ssfSettingsLogic'

type Props = SSFSettingsLogicProps & { disabledReason?: string | null }

export function SSFConnectionModal({ organizationId, disabledReason }: Props): JSX.Element {
    const logic = ssfSettingsLogic({ organizationId })
    const { connectionOpen, connection, isConnectionSubmitting } = useValues(logic)
    const { closeConnection } = useActions(logic)
    return (
        <LemonModal
            isOpen={connectionOpen}
            onClose={closeConnection}
            title={connection.id ? 'Edit SSF connection' : 'Add SSF connection'}
        >
            <Form
                logic={ssfSettingsLogic}
                props={{ organizationId }}
                formKey="connection"
                enableFormOnSubmit
                className="space-y-4 max-w-140"
            >
                <LemonField name="name" label="Connection name">
                    <LemonInput disabledReason={disabledReason} maxLength={200} data-attr="ssf-connection-name" />
                </LemonField>
                <LemonField name="direction" label="Direction">
                    <LemonSelect
                        options={[
                            {
                                value: SSFDirectionEnumApi.Incoming,
                                label: 'Incoming: receive events from a transmitter',
                            },
                            { value: SSFDirectionEnumApi.Outgoing, label: 'Outgoing: share events with a receiver' },
                        ]}
                        disabledReason={
                            disabledReason ||
                            (connection.id ? 'Create a new connection to change its identity.' : undefined)
                        }
                        data-attr="ssf-connection-direction"
                    />
                </LemonField>
                {connection.direction === SSFDirectionEnumApi.Incoming ? (
                    <>
                        <LemonField name="issuer" label="Trusted transmitter issuer">
                            <LemonInput
                                placeholder="https://idp.example.com"
                                disabledReason={
                                    disabledReason ||
                                    (connection.id ? 'Create a new connection to change its issuer.' : undefined)
                                }
                                data-attr="ssf-connection-issuer"
                            />
                        </LemonField>
                        <LemonField
                            name="remote_token"
                            label="Transmitter API bearer token"
                            help={
                                connection.id
                                    ? 'Leave blank to keep the saved token.'
                                    : 'Paste the token only, without the Bearer prefix.'
                            }
                        >
                            <LemonInput
                                type="password"
                                autoComplete="new-password"
                                className="ph-no-capture"
                                disabledReason={disabledReason}
                                data-attr="ssf-connection-token"
                            />
                        </LemonField>
                        <LemonBanner type="info">
                            PostHog discovers the transmitter's SSF endpoints and public signing keys from its issuer.
                            Incoming streams use push delivery. No manual key copying or stream ID entry is needed.
                        </LemonBanner>
                    </>
                ) : (
                    <>
                        <LemonField
                            name="audience"
                            label="Agreed receiver audience (optional)"
                            help="Leave blank to assign a unique audience to this receiver."
                        >
                            <LemonInput
                                disabledReason={
                                    disabledReason ||
                                    (connection.id ? 'Create a new connection to change its audience.' : undefined)
                                }
                                data-attr="ssf-connection-audience"
                            />
                        </LemonField>
                        <LemonBanner type="info">
                            This receiver gets its own management credential and can create multiple polling streams.
                            Its credential cannot access another connection's streams.
                        </LemonBanner>
                    </>
                )}
                <div className="flex justify-end gap-2 flex-wrap">
                    <LemonButton
                        type="secondary"
                        onClick={closeConnection}
                        disabledReason={isConnectionSubmitting ? 'Wait for this request to finish.' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isConnectionSubmitting}
                        disabledReason={disabledReason}
                        data-attr="ssf-save-connection"
                    >
                        {connection.id ? 'Save connection' : 'Add connection'}
                    </LemonButton>
                </div>
            </Form>
        </LemonModal>
    )
}
