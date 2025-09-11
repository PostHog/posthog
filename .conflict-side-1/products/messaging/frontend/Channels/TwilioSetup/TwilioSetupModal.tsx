import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconTwilio } from 'lib/lemon-ui/icons'

import { TwilioSetupModalLogicProps, twilioSetupModalLogic } from './twilioSetupModalLogic'

export const TwilioSetupModal = (props: TwilioSetupModalLogicProps): JSX.Element => {
    const { isTwilioIntegrationSubmitting } = useValues(twilioSetupModalLogic(props))
    const { submitTwilioIntegration } = useActions(twilioSetupModalLogic(props))

    return (
        <LemonModal
            title={
                <div className="flex items-center gap-2">
                    <IconTwilio />
                    <span>Configure Twilio SMS channel</span>
                </div>
            }
            onClose={props.onComplete}
        >
            <Form logic={twilioSetupModalLogic} formKey="twilioIntegration">
                <div className="gap-4 flex flex-col">
                    <LemonField name="accountSid" label="Account SID">
                        <LemonInput type="text" placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" />
                    </LemonField>
                    <LemonField name="authToken" label="Auth token">
                        <LemonInput type="password" />
                    </LemonField>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            loading={isTwilioIntegrationSubmitting}
                            onClick={submitTwilioIntegration}
                        >
                            Connect
                        </LemonButton>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
