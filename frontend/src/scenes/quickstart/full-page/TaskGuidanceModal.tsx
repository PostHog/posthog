import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { getProductIcon } from 'scenes/onboarding/shared/utils'

import { quickstartLogic } from '../quickstartLogic'
import { captureQuickstartAction } from '../shared/captureQuickstartAction'
import { PRODUCT_SDK_SETUP } from '../shared/productSdkSetup'

export function TaskGuidanceModal(): JSX.Element {
    const { selectedTask, enablingProducts } = useValues(quickstartLogic)
    const { closeTaskGuidance, enableProduct, openToolSetupModal } = useActions(quickstartLogic)

    const primaryAction = (): JSX.Element | null => {
        if (!selectedTask) {
            return null
        }

        const { product, step } = selectedTask
        const captureAction = (): void => {
            captureQuickstartAction('start_tool_task', product.key, {
                step_key: step.key,
                task_action: step.guide.action,
            })
        }

        if (step.guide.action === 'enable') {
            return (
                <LemonButton
                    type="primary"
                    loading={!!enablingProducts[product.key]}
                    disabledReason={step.achieved ? 'This is already enabled' : undefined}
                    onClick={() => {
                        captureAction()
                        enableProduct(product.key)
                    }}
                    data-attr="quickstart-task-enable"
                >
                    {step.achieved ? 'Enabled' : step.guide.actionLabel}
                </LemonButton>
            )
        }

        if (step.guide.action === 'setup' && PRODUCT_SDK_SETUP[product.key]) {
            return (
                <LemonButton
                    type="primary"
                    onClick={() => {
                        captureAction()
                        closeTaskGuidance()
                        openToolSetupModal(product.key)
                    }}
                    data-attr="quickstart-task-setup"
                >
                    {step.guide.actionLabel}
                </LemonButton>
            )
        }

        const destination =
            step.guide.action === 'docs'
                ? (step.guide.url ?? product.docsUrl ?? product.setupUrl)
                : step.guide.action === 'open_url'
                  ? (step.guide.url ?? product.url)
                  : step.guide.action === 'open_product'
                    ? product.url
                    : product.setupUrl

        return (
            <LemonButton
                type="primary"
                to={destination}
                targetBlank={step.guide.action === 'docs'}
                onClick={() => {
                    captureAction()
                    closeTaskGuidance()
                }}
                data-attr="quickstart-task-open"
            >
                {step.guide.actionLabel}
            </LemonButton>
        )
    }

    return (
        <LemonModal
            isOpen={!!selectedTask}
            onClose={closeTaskGuidance}
            title={selectedTask?.step.label ?? ''}
            width="32rem"
            footer={
                selectedTask && (
                    <div className="flex items-center justify-end gap-2">
                        <LemonButton onClick={closeTaskGuidance}>Close</LemonButton>
                        {primaryAction()}
                    </div>
                )
            }
        >
            {selectedTask && (
                <div className="flex flex-col gap-4">
                    <div className="flex items-center gap-2">
                        <span className="text-xl leading-none">
                            {getProductIcon(selectedTask.product.icon, { iconColor: selectedTask.product.iconColor })}
                        </span>
                        <span className="font-medium">{selectedTask.product.name}</span>
                        {selectedTask.step.achieved && <LemonTag type="success">Done</LemonTag>}
                    </div>
                    <p className="text-secondary mb-0">{selectedTask.step.guide.description}</p>
                    <div>
                        <div className="font-semibold mb-2">How to do it</div>
                        <ol className="flex flex-col gap-2 list-decimal pl-5 mb-0">
                            {selectedTask.step.guide.instructions.map((instruction) => (
                                <li key={instruction} className="pl-1">
                                    {instruction}
                                </li>
                            ))}
                        </ol>
                    </div>
                </div>
            )}
        </LemonModal>
    )
}
