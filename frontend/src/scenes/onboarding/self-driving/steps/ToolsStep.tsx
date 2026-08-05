import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { SELF_DRIVING_TOOLS, toolSetForGoal } from '../goals'
import { goalSelectionLogic } from '../goalSelectionLogic'
import { productEnablementStepLogic } from '../productEnablementStepLogic'

/**
 * Shows the goal's tool collection (see `toolSetForGoal`), already turned on by goal selection -
 * transparency, not a decision. The inline "Turn on" button appears only when an auto-enable call
 * failed (e.g. the toggle is admin-gated), so that failure path keeps a home without a screen per
 * product.
 */
export function ToolsStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { selectedGoal } = useValues(goalSelectionLogic)
    const { isSessionReplayEnabled, isErrorTrackingEnabled, enablingProduct, autoEnabling } =
        useValues(productEnablementStepLogic)
    const { enableProduct } = useActions(productEnablementStepLogic)

    const tools = toolSetForGoal(selectedGoal).shown.map((key) => SELF_DRIVING_TOOLS[key])

    return (
        <div className="flex flex-col gap-6 py-1">
            <p className="text-secondary text-center m-0">
                These are on and feeding your agents. You can change them later in settings.
            </p>
            <div className="flex flex-col gap-3">
                {tools.map((tool) => {
                    const colorVar = `var(--color-product-${tool.iconType.replace(/_/g, '-')}-light)`
                    const isOn = !tool.enablement
                        ? true
                        : tool.enablement === 'session_replay'
                          ? isSessionReplayEnabled
                          : isErrorTrackingEnabled
                    return (
                        <div
                            key={tool.name}
                            className="OnboardingProductCard flex items-center gap-4 p-4 rounded-lg border"
                        >
                            <div
                                className="size-12 shrink-0 rounded-lg flex items-center justify-center"
                                style={{ background: `color-mix(in srgb, ${colorVar} 12%, transparent)` }}
                            >
                                <div className="flex *:text-2xl group/colorful-product-icons colorful-product-icons-true">
                                    {iconForType(tool.iconType)}
                                </div>
                            </div>
                            <div className="flex-1 flex flex-col gap-0.5 min-w-0">
                                <div className="font-semibold text-base">{tool.name}</div>
                                <div className="text-sm text-secondary text-balance">{tool.benefit}</div>
                            </div>
                            {isOn ? (
                                <div className="flex items-center gap-1.5 text-sm text-success shrink-0">
                                    <span className="size-2 rounded-full bg-success" />
                                    Enabled
                                </div>
                            ) : (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    loading={autoEnabling || enablingProduct === tool.enablement}
                                    onClick={() => tool.enablement && enableProduct(tool.enablement)}
                                >
                                    Turn on
                                </LemonButton>
                            )}
                        </div>
                    )
                })}
            </div>
            <div className="flex justify-center">
                <LemonButton type="primary" status="alt" onClick={onContinue}>
                    Continue
                </LemonButton>
            </div>
        </div>
    )
}
