import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonDialog, LemonModal, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { SSFConnectionModal } from './SSFConnectionModal'
import { SSFConnections } from './SSFConnections'
import { SSFSettingsLogicProps, ssfSettingsLogic } from './ssfSettingsLogic'
import { SSFStreamModal } from './SSFStreamModal'
import { SSFStreams } from './SSFStreams'
import { SSFSubjectModal } from './SSFSubjectModal'

export function SSFConfiguration({ organizationId }: SSFSettingsLogicProps): JSX.Element {
    const logic = ssfSettingsLogic({ organizationId })
    const { configuration, configurationLoading, loadError, isSsfSubmitting, isWorking, credential } = useValues(logic)
    const { loadConfiguration, setEnabled, rotateSigningKey, clearCredential } = useActions(logic)
    const restriction = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const disabledReason = restriction || (isWorking ? 'Wait for the current request to finish.' : undefined)

    if (!configuration && !loadError) {
        return <LemonSkeleton className="h-40" />
    }
    if (loadError || !configuration) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadConfiguration }}>
                Could not load SSF settings. Try again, or contact support if the problem continues.
            </LemonBanner>
        )
    }
    return (
        <div className="space-y-6 max-w-240">
            <p>
                Connect trusted security services to this organization using the Shared Signals Framework (SSF). Each
                connection can have multiple streams with separate event subscriptions and delivery settings.
            </p>
            {restriction && (
                <LemonBanner type="info">Only organization admins and owners can edit SSF settings.</LemonBanner>
            )}
            <LemonSwitch
                label="Enable SSF"
                checked={!!configuration.enabled}
                onChange={(enabled) => setEnabled({ enabled })}
                loading={configurationLoading}
                disabledReason={disabledReason}
                bordered
                data-attr="ssf-enabled"
            />
            {configuration.enabled && (
                <>
                    <Form
                        logic={ssfSettingsLogic}
                        props={{ organizationId }}
                        formKey="ssf"
                        enableFormOnSubmit
                        className="space-y-4"
                    >
                        <LemonField
                            name="eventTypes"
                            label="Additional outgoing event types"
                            info="Choose from the basic CAEP and RISC event types. Verification and stream status events are supported automatically. Delete outgoing streams before changing this list."
                        >
                            <LemonInputSelect
                                mode="multiple"
                                options={[...configuration.event_type_options]}
                                allowCustomValues={false}
                                disableEditing
                                placeholder="Select outgoing event types"
                                disabledReason={disabledReason}
                                data-attr="ssf-event-types"
                            />
                        </LemonField>
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isSsfSubmitting}
                            disabledReason={disabledReason}
                            data-attr="ssf-save"
                        >
                            Save
                        </LemonButton>
                    </Form>
                    <SSFConnections organizationId={organizationId} disabledReason={disabledReason} />
                    <SSFStreams organizationId={organizationId} disabledReason={disabledReason} />
                    <section className="space-y-3">
                        <h3>Transmitter discovery</h3>
                        <p className="text-secondary">
                            Give external receivers this discovery URL and their connection's management credential.
                            They can create and manage their own polling streams through the SSF API.
                        </p>
                        <div className="flex items-start gap-2">
                            <code className="min-w-0 break-all">{configuration.endpoints.discovery_url}</code>
                            <CopyToClipboardInline explicitValue={configuration.endpoints.discovery_url} />
                        </div>
                        <LemonButton
                            type="secondary"
                            disabledReason={disabledReason}
                            data-attr="ssf-rotate-signing-key"
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Rotate the signing key?',
                                    description:
                                        'New outgoing events will use a new signing key. Previous public keys remain available for the event retention window.',
                                    primaryButton: { children: 'Rotate signing key', onClick: rotateSigningKey },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                        >
                            Rotate signing key
                        </LemonButton>
                    </section>
                    <SSFConnectionModal organizationId={organizationId} disabledReason={disabledReason} />
                    <SSFStreamModal organizationId={organizationId} disabledReason={disabledReason} />
                    <SSFSubjectModal organizationId={organizationId} disabledReason={disabledReason} />
                    <LemonModal
                        isOpen={!!credential}
                        onClose={clearCredential}
                        title="SSF management credential"
                        footer={
                            <LemonButton type="primary" onClick={clearCredential}>
                                Done
                            </LemonButton>
                        }
                    >
                        <LemonBanner type="warning">
                            Copy this credential now. You cannot view it again. The receiver sends it in the
                            Authorization header using the Bearer scheme. It only grants access to this connection's
                            streams.
                        </LemonBanner>
                        {credential && (
                            <div className="ph-no-capture ph-mask mt-4">
                                <CodeSnippet language={Language.Text}>{credential.token}</CodeSnippet>
                            </div>
                        )}
                    </LemonModal>
                </>
            )}
        </div>
    )
}
