import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { AzureBlobSetupModalLogicProps, azureBlobSetupModalLogic } from './azureBlobSetupModalLogic'

export const AzureBlobSetupModal = (props: AzureBlobSetupModalLogicProps): JSX.Element => {
    const { isAzureBlobIntegrationSubmitting } = useValues(azureBlobSetupModalLogic(props))
    const { submitAzureBlobIntegration } = useActions(azureBlobSetupModalLogic(props))

    return (
        <LemonModal
            isOpen={props.isOpen}
            title="Configure Azure Blob Storage"
            description="Enter your Azure Storage connection string to connect PostHog to your Azure Blob Storage account."
            onClose={props.onComplete}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => props.onComplete()}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isAzureBlobIntegrationSubmitting}
                        onClick={submitAzureBlobIntegration}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form logic={azureBlobSetupModalLogic} formKey="azureBlobIntegration">
                <LemonField
                    name="connectionString"
                    label="Connection string"
                    info={
                        <>
                            Find your connection string in the Azure Portal under Storage Account &rarr; Access keys. It
                            starts with "DefaultEndpointsProtocol=https;AccountName=...".
                        </>
                    }
                >
                    <LemonInput
                        type="password"
                        placeholder="DefaultEndpointsProtocol=https;AccountName=..."
                        className="ph-ignore-input"
                    />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
