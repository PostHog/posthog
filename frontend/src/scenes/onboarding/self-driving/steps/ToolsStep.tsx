import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { getTreeItemsProducts } from '~/products'

import {
    DOCS_URL_BY_PRODUCT_PATH,
    ONBOARDING_TOOLS,
    resolveSetup,
    toolEnablement,
    toolIconType,
} from '../../shared/useCases'
import { productEnablementStepLogic } from '../productEnablementStepLogic'
import { useCaseSelectionLogic } from '../useCaseSelectionLogic'

/**
 * Shows the use case's tool collection, already turned on by use-case selection - transparency,
 * not a decision. The inline "Turn on" button appears only when an auto-enable call failed (e.g.
 * the toggle is admin-gated), so that failure path keeps a home without a screen per product.
 */
export function ToolsStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { selectedUseCase } = useValues(useCaseSelectionLogic)
    const { isSessionReplayEnabled, isErrorTrackingEnabled, enablingProduct, autoEnabling } =
        useValues(productEnablementStepLogic)
    const { enableProduct } = useActions(productEnablementStepLogic)

    const setup = resolveSetup(selectedUseCase)
    const tools = setup.tools.map((key) => ONBOARDING_TOOLS[key])
    // The setup's sidebar extras, resolved the same way the backend populates the sidebar:
    // through the products registry's `intents`. Tools already shown above are excluded.
    const shownNames = new Set(tools.map((tool) => tool.productPath))
    const sidebarExtras = getTreeItemsProducts().filter(
        (item) =>
            item.intents?.some((intent) => setup.sidebarExtras.includes(intent)) &&
            typeof item.path === 'string' &&
            !shownNames.has(item.path)
    )

    return (
        <div className="flex flex-col gap-6 py-1">
            <p className="text-secondary text-center m-0">
                These are on and feeding your agents. You can change them later in settings.
            </p>
            <div className="flex flex-col gap-3">
                {tools.map((tool) => {
                    const iconType = toolIconType(tool)
                    const colorVar = `var(--color-product-${iconType.replace(/_/g, '-')}-light)`
                    const enablement = toolEnablement(tool)
                    const isOn = !enablement
                        ? true
                        : enablement === 'session_replay'
                          ? isSessionReplayEnabled
                          : isErrorTrackingEnabled
                    return (
                        <div
                            key={tool.productPath}
                            className="OnboardingProductCard flex items-center gap-4 p-4 rounded-lg border"
                        >
                            <div
                                className="size-12 shrink-0 rounded-lg flex items-center justify-center"
                                style={{ background: `color-mix(in srgb, ${colorVar} 12%, transparent)` }}
                            >
                                <div className="flex *:text-2xl group/colorful-product-icons colorful-product-icons-true">
                                    {iconForType(iconType)}
                                </div>
                            </div>
                            <div className="flex-1 flex flex-col gap-0.5 min-w-0">
                                <div className="font-semibold text-base">{tool.productPath}</div>
                                <div className="text-sm text-secondary text-balance">
                                    {tool.benefit}{' '}
                                    <Link
                                        to={DOCS_URL_BY_PRODUCT_PATH[tool.productPath]}
                                        target="_blank"
                                        className="whitespace-nowrap"
                                    >
                                        Read the docs
                                    </Link>
                                </div>
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
                                    loading={autoEnabling || enablingProduct === enablement}
                                    onClick={() => enablement && enableProduct(enablement)}
                                >
                                    Turn on
                                </LemonButton>
                            )}
                        </div>
                    )
                })}
            </div>
            {sidebarExtras.length > 0 && (
                <div className="flex flex-wrap items-center justify-center gap-2">
                    <span className="text-xs text-muted">Also in your sidebar:</span>
                    {sidebarExtras.map((item) => {
                        const tag = (
                            <LemonTag
                                icon={
                                    item.iconType ? (
                                        <span className="flex group/colorful-product-icons colorful-product-icons-true">
                                            {iconForType(item.iconType)}
                                        </span>
                                    ) : undefined
                                }
                            >
                                {item.path}
                            </LemonTag>
                        )
                        const docsUrl = DOCS_URL_BY_PRODUCT_PATH[item.path]
                        return docsUrl ? (
                            <Link key={item.path} to={docsUrl} target="_blank">
                                {tag}
                            </Link>
                        ) : (
                            <span key={item.path}>{tag}</span>
                        )
                    })}
                </div>
            )}
            <div className="flex justify-center">
                <LemonButton type="primary" status="alt" onClick={onContinue}>
                    Continue
                </LemonButton>
            </div>
        </div>
    )
}
