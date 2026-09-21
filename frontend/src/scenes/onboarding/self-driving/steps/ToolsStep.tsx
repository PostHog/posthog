import { useValues } from 'kea'

import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { toSentenceCase } from 'scenes/onboarding/shared/utils'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { getTreeItemsProducts } from '~/products'

import {
    ADDITIONAL_TOOL_DETAILS,
    DOCS_URL_BY_PRODUCT_PATH,
    ONBOARDING_TOOLS,
    resolveSetup,
    toolIconType,
} from '../../shared/useCases'
import { useCaseSelectionLogic } from '../useCaseSelectionLogic'

export function ToolsStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { selectedUseCase } = useValues(useCaseSelectionLogic)

    const setup = resolveSetup(selectedUseCase)
    const setupTools = setup.tools.map((key) => ONBOARDING_TOOLS[key])
    const setupProductKeys = new Set(setupTools.map((tool) => tool.productKey))
    const tools = [
        ...setupTools.map((tool) => ({
            productKey: tool.productKey,
            name: tool.displayName ?? tool.productPath,
            description: tool.benefit,
            docsUrl: DOCS_URL_BY_PRODUCT_PATH[tool.productPath],
            iconType: toolIconType(tool),
        })),
        ...(setup.additionalTools ?? [])
            .filter((productKey) => !setupProductKeys.has(productKey))
            .map((productKey) => {
                const productItem = getTreeItemsProducts().find((item) => item.intents?.includes(productKey))
                const details = ADDITIONAL_TOOL_DETAILS[productKey]
                const tool = {
                    name: productItem?.path ?? productKey,
                    description: details?.description ?? '',
                }
                return {
                    productKey,
                    name: toSentenceCase(tool.name),
                    description: tool.description,
                    docsUrl: details?.docsUrl ?? DOCS_URL_BY_PRODUCT_PATH[tool.name],
                    iconType: productItem?.iconType ?? 'product_analytics',
                }
            }),
    ]
    // The setup's sidebar extras, resolved the same way the backend populates the sidebar:
    // through the products registry's `intents`. Tools already shown above are excluded.
    const shownNames = new Set(tools.map((tool) => tool.name))
    const sidebarExtras = getTreeItemsProducts().filter(
        (item) =>
            item.intents?.some((intent) => setup.sidebarExtras.includes(intent)) &&
            typeof item.path === 'string' &&
            !shownNames.has(item.path)
    )

    return (
        <div className="flex flex-col gap-6 py-1">
            <p className="text-secondary text-center m-0">
                These tools will feed your agents after setup finishes. You can change them later in settings.
            </p>
            <div className="flex flex-col gap-2">
                {tools.map((tool) => {
                    const iconType = tool.iconType
                    const colorVar = `var(--color-product-${iconType.replace(/_/g, '-')}-light)`

                    return (
                        <div
                            key={tool.productKey}
                            className="OnboardingProductCard flex items-start gap-4 px-4 rounded-lg"
                        >
                            <div
                                className="size-8 shrink-0 rounded-lg flex items-center justify-center"
                                style={{ background: `color-mix(in srgb, ${colorVar} 12%, transparent)` }}
                            >
                                <div className="flex *:text-xl group/colorful-product-icons colorful-product-icons-true">
                                    {iconForType(iconType)}
                                </div>
                            </div>
                            <div className="flex-1 flex flex-col gap-1 min-w-0">
                                <div className="font-semibold text-base">{tool.name}</div>
                                <div className="text-sm text-secondary text-balance">{tool.description}</div>
                                <Link to={tool.docsUrl} target="_blank" className="text-sm w-fit">
                                    Read the docs
                                </Link>
                            </div>
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
