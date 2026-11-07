import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { projectLogic } from 'scenes/projectLogic'
import { userLogic } from 'scenes/userLogic'

import { wizardSpendAuditLogic } from 'products/wizard/frontend/views/spend-audit/wizardSpendAuditLogic'
import { WizardSpendAuditModal } from 'products/wizard/frontend/views/spend-audit/WizardSpendAuditModal'

function OptimizeSpendCtaForProject({ projectId, userId }: { projectId: string; userId: number }): JSX.Element | null {
    const logic = wizardSpendAuditLogic({ projectId, userId })
    const { enabled } = useValues(logic)
    const { openModal } = useActions(logic)

    if (!enabled) {
        return null
    }

    return (
        <div className="mt-6 max-w-300">
            <div
                className="flex flex-wrap items-center justify-between gap-4 rounded-lg border bg-surface-primary p-4"
                data-attr="billing-optimize-spend"
            >
                <div className="min-w-0 flex-1">
                    <h3 className="mb-1">Find savings in your setup</h3>
                    <p className="mb-0 text-secondary">
                        The setup agent audits how your code sends data to PostHog and opens a pull request with changes
                        that lower your bill.
                    </p>
                </div>
                <LemonButton
                    type="primary"
                    icon={<IconSparkles />}
                    onClick={() => openModal('billing_button')}
                    data-attr="billing-optimize-spend-button"
                >
                    Optimize my spend
                </LemonButton>
            </div>
            <WizardSpendAuditModal projectId={projectId} userId={userId} />
        </div>
    )
}

export function OptimizeSpendCta(): JSX.Element | null {
    const { currentProjectId } = useValues(projectLogic)
    const { user } = useValues(userLogic)

    if (!currentProjectId || !user) {
        return null
    }

    return <OptimizeSpendCtaForProject projectId={String(currentProjectId)} userId={user.id} />
}
