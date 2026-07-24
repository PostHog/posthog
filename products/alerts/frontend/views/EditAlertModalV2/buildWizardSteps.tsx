import type { ReactNode } from 'react'

import { AlertWizardStep } from 'products/alerts/frontend/components/AlertWizard'

interface WizardStepInput {
    nameNode: ReactNode
    definitionNode: ReactNode
    previewNode: ReactNode
    scheduleNode: ReactNode
    notifyNode: ReactNode
    advancedNode: ReactNode
    summary: { fires: string; cadence: string; notifies: string }
    thresholdBoundsFormError?: string
    scheduleRestrictionFormError?: string
    alertFormHasErrors: boolean
    alertName: string
}

export function buildWizardSteps(input: WizardStepInput): AlertWizardStep[] {
    const { summary, alertFormHasErrors } = input
    const reviewFires = summary.fires || 'a configured threshold'
    const reviewCadence = summary.cadence || 'a cadence'
    const reviewNotifies = summary.notifies || 'no one yet'
    const monitorCannotAdvanceReason = !input.alertName ? 'Enter an alert name.' : input.thresholdBoundsFormError
    const monitorCanAdvance = !monitorCannotAdvanceReason

    return [
        {
            key: 'monitor',
            title: 'Monitor',
            description: 'Pick what this alert watches and when it should fire.',
            canAdvance: monitorCanAdvance,
            cannotAdvanceReason: monitorCannotAdvanceReason,
            content: (
                <div className="space-y-4">
                    {input.nameNode}
                    {input.previewNode}
                    {input.definitionNode}
                </div>
            ),
        },
        {
            key: 'schedule',
            title: 'Schedule',
            description: 'How often this alert runs.',
            canAdvance: !input.scheduleRestrictionFormError,
            cannotAdvanceReason: input.scheduleRestrictionFormError,
            content: (
                <div className="space-y-3">
                    {input.scheduleNode}
                    {input.advancedNode}
                </div>
            ),
        },
        {
            key: 'notify',
            title: 'Notify',
            description: 'Who gets told when this alert fires.',
            canAdvance: true,
            content: <div className="space-y-4">{input.notifyNode}</div>,
        },
        {
            key: 'review',
            title: 'Review',
            description: 'Confirm what this alert will do, then create it.',
            canAdvance: !alertFormHasErrors,
            cannotAdvanceReason: alertFormHasErrors ? 'Fix the errors in previous steps before creating.' : undefined,
            content: (
                <div className="space-y-3">
                    <div className="rounded border border-border bg-bg-light p-3 space-y-1.5 text-sm">
                        <div className="flex gap-2">
                            <span className="text-muted w-20 shrink-0">Fires when</span>
                            <span className="font-medium">{reviewFires}</span>
                        </div>
                        <div className="flex gap-2">
                            <span className="text-muted w-20 shrink-0">Runs</span>
                            <span className="font-medium">{reviewCadence}</span>
                        </div>
                        <div className="flex gap-2">
                            <span className="text-muted w-20 shrink-0">Notifies</span>
                            <span className="font-medium">{reviewNotifies}</span>
                        </div>
                    </div>
                    <p className="text-xs text-muted">
                        You can adjust any of this later without stepping through the wizard. Editing an existing alert
                        opens straight to its sections.
                    </p>
                </div>
            ),
        },
    ]
}
