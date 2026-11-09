import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { SSFDirectionEnumApi } from '~/generated/core/api.schemas'

import { SSFSettingsLogicProps, ssfSettingsLogic } from './ssfSettingsLogic'

type Props = SSFSettingsLogicProps & { disabledReason?: string | null }

export function SSFStreamModal({ organizationId, disabledReason }: Props): JSX.Element {
    const logic = ssfSettingsLogic({ organizationId })
    const { streamOpen, stream, connections, configuration, isStreamSubmitting } = useValues(logic)
    const { closeStream } = useActions(logic)
    return (
        <LemonModal isOpen={streamOpen} onClose={closeStream} title={stream.id ? 'Edit SSF stream' : 'Add SSF stream'}>
            <Form
                logic={ssfSettingsLogic}
                props={{ organizationId }}
                formKey="stream"
                enableFormOnSubmit
                className="space-y-4 max-w-140"
            >
                <LemonField name="connection" label="Connection">
                    <LemonSelect
                        options={(connections || []).map((peer) => ({
                            value: peer.id,
                            label: `${peer.name} (${peer.direction === SSFDirectionEnumApi.Incoming ? 'incoming' : 'outgoing'})`,
                        }))}
                        disabledReason={
                            disabledReason || (stream.id ? 'A stream stays with its connection.' : undefined)
                        }
                        data-attr="ssf-stream-connection"
                    />
                </LemonField>
                <LemonField name="description" label="Stream description">
                    <LemonInput disabledReason={disabledReason} maxLength={1024} data-attr="ssf-stream-description" />
                </LemonField>
                <LemonField
                    name="eventTypes"
                    label="Requested event types"
                    help="Select from the basic CAEP and RISC event types. If none are selected, new streams request only SSF control events."
                >
                    <LemonInputSelect
                        mode="multiple"
                        options={[...(configuration?.event_type_options || [])]}
                        allowCustomValues={false}
                        disableEditing
                        placeholder="Select event types"
                        disabledReason={disabledReason}
                        data-attr="ssf-stream-event-types"
                    />
                </LemonField>
                <LemonBanner type="info">
                    For incoming streams, PostHog creates the stream at the transmitter, configures a dedicated receiver
                    endpoint, and requests verification when supported. Add subject subscriptions after setup to select
                    whose events you receive.
                </LemonBanner>
                <div className="flex justify-end gap-2 flex-wrap">
                    <LemonButton
                        type="secondary"
                        onClick={closeStream}
                        disabledReason={isStreamSubmitting ? 'Wait for this request to finish.' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        loading={isStreamSubmitting}
                        disabledReason={disabledReason}
                        data-attr="ssf-save-stream"
                    >
                        {stream.id ? 'Save stream' : 'Add stream'}
                    </LemonButton>
                </div>
            </Form>
        </LemonModal>
    )
}
