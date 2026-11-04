import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { AwsRoleArnByRegion, AwsRoleRequirements } from 'scenes/integrations/components/AwsRoleRequirements'

import { Region } from '~/types'

import {
    AwsWarehouseSourcesSetupModalLogicProps,
    awsWarehouseSourcesSetupModalLogic,
} from './awsWarehouseSourcesSetupModalLogic'

// Mirrors WAREHOUSE_SOURCES_AWS_ROLE_ARN per region.
const WAREHOUSE_SOURCES_ROLE_ARN_BY_REGION: AwsRoleArnByRegion = {
    [Region.US]: 'arn:aws:iam::309986977637:role/posthog-external-warehouse-sources',
    [Region.EU]: 'arn:aws:iam::623789312881:role/posthog-external-warehouse-sources',
}

export const AwsWarehouseSourcesSetupModal = (props: AwsWarehouseSourcesSetupModalLogicProps): JSX.Element => {
    const logic = awsWarehouseSourcesSetupModalLogic(props)
    const { isAwsWarehouseSourcesIntegrationSubmitting } = useValues(logic)
    const { submitAwsWarehouseSourcesIntegration } = useActions(logic)

    return (
        <LemonModal
            isOpen={props.isOpen}
            title="Configure AWS role connection"
            description="Let PostHog read your AWS data through an IAM role. Connections can be reused across sources."
            onClose={props.onComplete}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => props.onComplete()}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={isAwsWarehouseSourcesIntegrationSubmitting}
                        onClick={submitAwsWarehouseSourcesIntegration}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={awsWarehouseSourcesSetupModalLogic}
                props={props}
                formKey="awsWarehouseSourcesIntegration"
                className="flex flex-col gap-4"
            >
                <LemonField name="name" label="Name" info="A name to identify this connection across sources.">
                    <LemonInput placeholder="e.g. Production account" />
                </LemonField>
                <LemonField
                    name="awsRoleArn"
                    label="IAM role ARN"
                    info="The ARN of an IAM role in your AWS account that PostHog will assume to read your data."
                >
                    <LemonInput
                        placeholder="e.g. arn:aws:iam::123456789012:role/posthog-warehouse-sources"
                        autoComplete="off"
                    />
                </LemonField>
                <AwsRoleRequirements
                    posthogRoleArnByRegion={WAREHOUSE_SOURCES_ROLE_ARN_BY_REGION}
                    jobs="syncs"
                    permissions={
                        <>
                            Grant the role the read permissions listed in the source's setup instructions. PostHog only
                            reads, so the role needs no write access.
                        </>
                    }
                />
            </Form>
        </LemonModal>
    )
}
