import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { partnerBillingApplicationsLogic } from './partnerBillingApplicationsLogic'
import { PartnerBillingPayer } from './PartnerBillingPayer'

export function PartnerBilling(): JSX.Element {
    const {
        partnerBillingApplications,
        partnerBillingApplicationsError,
        partnerBillingApplicationsLoading,
        selectedApplication,
    } = useValues(partnerBillingApplicationsLogic)
    const { ensurePartnerBillingApplications, loadPartnerBillingApplications, selectApplication } = useActions(
        partnerBillingApplicationsLogic
    )
    useOnMountEffect(() => {
        ensurePartnerBillingApplications()
    })

    if (!partnerBillingApplications) {
        return partnerBillingApplicationsError && !partnerBillingApplicationsLoading ? (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: () => loadPartnerBillingApplications(),
                    'data-attr': 'partner-billing-reload-applications',
                }}
            >
                {partnerBillingApplicationsError}
            </LemonBanner>
        ) : (
            <LemonSkeleton className="h-32" />
        )
    }

    if (!selectedApplication) {
        return <p className="text-secondary">This organization doesn't manage billing for any partner application.</p>
    }

    return (
        <div className="flex flex-col gap-6">
            {partnerBillingApplications.length > 1 && (
                <LemonField.Pure label="Partner application" className="max-w-80">
                    <LemonSelect
                        value={selectedApplication.id}
                        onChange={selectApplication}
                        options={partnerBillingApplications.map((application) => ({
                            value: application.id,
                            label: application.name,
                        }))}
                        data-attr="partner-billing-select-application"
                    />
                </LemonField.Pure>
            )}
            <PartnerBillingPayer key={selectedApplication.id} application={selectedApplication} />
        </div>
    )
}
