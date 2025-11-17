import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconDatabricks } from 'lib/lemon-ui/icons'

import { DatabricksSetupModalLogicProps, databricksSetupModalLogic } from './databricksSetupModalLogic'

export const DatabricksSetupModal = (props: DatabricksSetupModalLogicProps): JSX.Element => {
    const { isDatabricksIntegrationSubmitting } = useValues(databricksSetupModalLogic(props))
    const { submitDatabricksIntegration } = useActions(databricksSetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            title={
                <div className="flex items-center gap-2">
                    <IconDatabricks />
                    <span>Configure Databricks integration</span>
                </div>
            }
            onClose={props.onComplete}
        >
            <Form logic={databricksSetupModalLogic} formKey="databricksIntegration">
                <div className="gap-4 flex flex-col">
                    <LemonField name="serverHostname" label="Server Hostname">
                        <LemonInput type="text" placeholder="dbc-xxxxxxxxx-xxxx.cloud.databricks.com" />
                    </LemonField>
                    <LemonField name="clientId" label="Client ID">
                        <LemonInput type="text" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
                    </LemonField>
                    <LemonField name="clientSecret" label="Client Secret">
                        <LemonInput type="password" />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isDatabricksIntegrationSubmitting}
                            onClick={submitDatabricksIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
