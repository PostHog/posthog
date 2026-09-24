import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { ClickHouseSetupModalLogicProps, clickHouseSetupModalLogic } from './clickHouseSetupModalLogic'

export const ClickHouseSetupModal = (props: ClickHouseSetupModalLogicProps): JSX.Element => {
    const { isClickHouseIntegrationSubmitting } = useValues(clickHouseSetupModalLogic(props))
    const { submitClickHouseIntegration } = useActions(clickHouseSetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            width={560}
            title="Configure ClickHouse connection"
            description="PostHog connects over HTTPS. The password is stored encrypted and the connection can be reused."
            onClose={props.onComplete}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => props.onComplete()}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isClickHouseIntegrationSubmitting}
                        onClick={submitClickHouseIntegration}
                        data-attr="clickhouse-integration-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={clickHouseSetupModalLogic}
                props={props}
                formKey="clickHouseIntegration"
                className="flex flex-col gap-4"
            >
                <LemonField
                    name="name"
                    label="Name"
                    showOptional
                    info="What this connection is called wherever PostHog lists it. Without one, PostHog shows the user and host."
                >
                    <LemonInput placeholder="Analytics cluster" />
                </LemonField>
                <div className="flex gap-2">
                    <LemonField name="host" label="Host" className="flex-1">
                        <LemonInput placeholder="abc123.us-east-1.aws.clickhouse.cloud" autoComplete="off" />
                    </LemonField>
                    <LemonField name="port" label="HTTPS port" className="w-28">
                        <LemonInput type="number" min={1} max={65535} />
                    </LemonField>
                </div>
                <LemonField name="user" label="User">
                    <LemonInput placeholder="default" autoComplete="off" />
                </LemonField>
                <LemonField name="password" label="Password">
                    <LemonInput type="password" autoComplete="new-password" />
                </LemonField>
                <LemonField
                    name="verify"
                    info="Turn this off only for a self-hosted server with a self-signed certificate. The connection stays encrypted either way."
                >
                    {({ value, onChange }) => (
                        <LemonCheckbox
                            bordered
                            checked={!!value}
                            onChange={onChange}
                            label="Verify the server certificate"
                        />
                    )}
                </LemonField>
            </Form>
        </LemonModal>
    )
}
