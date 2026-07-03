import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconNotebook, IconPlus } from '@posthog/icons'
import { LemonButton, LemonCard, LemonModal, LemonSkeleton, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { planCreateLogic } from '../../logics/planCreateLogic'
import { planListLogic } from '../../logics/planListLogic'

function NewPlanModal(): JSX.Element {
    const { newPlanModalOpen, descriptionDraft, creating } = useValues(planCreateLogic)
    const { closeNewPlanModal, setDescriptionDraft, createPlan } = useActions(planCreateLogic)

    return (
        <LemonModal
            isOpen={newPlanModalOpen}
            onClose={closeNewPlanModal}
            title="New plan"
            description="Briefly describe the feature or change you want to plan — you'll flesh it out with an agent next."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeNewPlanModal}
                        disabledReason={creating ? 'Creating…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={createPlan}
                        loading={creating}
                        disabledReason={!descriptionDraft.trim() ? 'Describe the idea first' : undefined}
                    >
                        Start planning
                    </LemonButton>
                </>
            }
        >
            <LemonTextArea
                value={descriptionDraft}
                onChange={setDescriptionDraft}
                minRows={3}
                placeholder="e.g. A burndown chart widget for dashboards, driven by error tracking issues"
                autoFocus
            />
        </LemonModal>
    )
}

export function PlanTab(): JSX.Element {
    const { plans, plansLoading } = useValues(planListLogic)
    const { openNewPlanModal } = useActions(planCreateLogic)

    const newPlanButton = (
        <LemonButton type="primary" size="small" icon={<IconPlus />} onClick={openNewPlanModal}>
            New plan
        </LemonButton>
    )

    if (plansLoading && plans.length === 0) {
        return (
            <div className="flex flex-col gap-2 p-6">
                <LemonSkeleton className="h-16 rounded" repeat={3} />
            </div>
        )
    }

    if (plans.length === 0) {
        return (
            <>
                <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted">
                    <IconNotebook className="text-2xl" />
                    <h3 className="mb-0">No plans yet</h3>
                    <p className="max-w-md text-sm">
                        Plans are projects you scope out with an agent before implementation.
                    </p>
                    {newPlanButton}
                </div>
                <NewPlanModal />
            </>
        )
    }

    return (
        <div className="flex flex-col gap-2 p-6">
            <div className="flex items-center justify-end">{newPlanButton}</div>
            {plans.map((plan) => (
                <LemonCard
                    key={plan.id}
                    onClick={() => router.actions.push(urls.inboxReport('plan', plan.id))}
                    className="flex flex-col gap-1"
                >
                    <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold">{plan.title || 'Untitled plan'}</span>
                        {plan.is_draft ? <LemonTag type="warning">Draft</LemonTag> : <LemonTag>{plan.status}</LemonTag>}
                    </div>
                    {plan.summary && <span className="line-clamp-2 text-sm text-muted">{plan.summary}</span>}
                    <TZLabel time={plan.updated_at} className="text-xs text-muted" />
                </LemonCard>
            ))}
            <NewPlanModal />
        </div>
    )
}
