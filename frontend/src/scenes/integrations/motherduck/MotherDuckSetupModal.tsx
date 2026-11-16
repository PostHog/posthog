import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { MotherDuckSetupModalLogicProps, motherDuckSetupModalLogic } from './motherDuckSetupModalLogic'

export const MotherDuckSetupModal = (props: MotherDuckSetupModalLogicProps): JSX.Element => {
    const { isMotherDuckIntegrationSubmitting } = useValues(motherDuckSetupModalLogic(props))
    const { submitMotherDuckIntegration } = useActions(motherDuckSetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            width={560}
            title="Configure MotherDuck connection"
            description="Enter a MotherDuck access token to connect PostHog to your account. It is stored encrypted and can be reused across destinations."
            onClose={props.onComplete}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => props.onComplete()}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isMotherDuckIntegrationSubmitting}
                        onClick={submitMotherDuckIntegration}
                        data-attr="motherduck-integration-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form logic={motherDuckSetupModalLogic} formKey="motherDuckIntegration" className="flex flex-col gap-4">
                <LemonField name="name" label="Name" info="A name to identify this connection across destinations.">
                    <LemonInput placeholder="e.g. Production MotherDuck account" />
                </LemonField>
                <LemonField name="access_token" label="Access token">
                    <LemonInput type="password" placeholder="my-access-token" autoComplete="new-password" />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
