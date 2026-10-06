import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { PartnerBillingLimitFields } from './PartnerBillingLimitFields'
import { PartnerBillingLogicProps, partnerBillingLogic } from './partnerBillingLogic'
import { partnerBillingOrganizationsLogic } from './partnerBillingOrganizationsLogic'

export function PartnerBillingOrganizationLimitsModal({ applicationId }: PartnerBillingLogicProps): JSX.Element {
    const logic = partnerBillingOrganizationsLogic({ applicationId })
    const {
        editingOrganization,
        editingLimitProducts,
        editingLimitPlaceholders,
        isOrganizationLimitsFormSubmitting,
        organizationLimitsFormHasChanges,
    } = useValues(logic)
    const { closeOrganizationLimits, submitOrganizationLimitsForm } = useActions(logic)
    const { billingLoading } = useValues(partnerBillingLogic({ applicationId }))

    return (
        <LemonModal
            isOpen={!!editingOrganization}
            onClose={closeOrganizationLimits}
            title={`Monthly limits for ${editingOrganization?.name ?? 'this organization'}`}
            description="Spend limits per product in whole US dollars. An empty field shows the limit that applies to that product. Clearing a limit means no limit for that product, even if you set a default."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeOrganizationLimits}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => submitOrganizationLimitsForm()}
                        loading={isOrganizationLimitsFormSubmitting}
                        disabledReason={!organizationLimitsFormHasChanges ? 'No changes to save' : undefined}
                        data-attr="partner-billing-save-organization-limits"
                    >
                        Save limits
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={partnerBillingOrganizationsLogic}
                props={{ applicationId }}
                formKey="organizationLimitsForm"
                enableFormOnSubmit
            >
                <PartnerBillingLimitFields
                    fieldName="custom_limits_usd"
                    products={editingLimitProducts}
                    productsLoading={billingLoading}
                    placeholders={editingLimitPlaceholders}
                />
            </Form>
        </LemonModal>
    )
}
