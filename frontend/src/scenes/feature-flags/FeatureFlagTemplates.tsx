import { useActions, useValues } from 'kea'

import { IconFlask, IconPeople, IconTestTube, IconToggle, IconX } from '@posthog/icons'
import { LemonButton, LemonCollapse, Tooltip } from '@posthog/lemon-ui'

import { featureFlagLogic } from './featureFlagLogic'

export type ModifiedField = 'key' | 'flagType' | 'rollout' | 'conditions'

interface TemplateFieldHighlightProps {
    field: ModifiedField
    highlightedFields: ModifiedField[]
    onClearHighlight?: (field: ModifiedField) => void
    children: React.ReactNode
    className?: string
}

/**
 * Wraps a field to show a tooltip indicating it was set by a template.
 * The tooltip stays visible until the user clicks to dismiss it.
 */
export function TemplateFieldHighlight({
    field,
    highlightedFields,
    onClearHighlight,
    children,
    className = '',
}: TemplateFieldHighlightProps): JSX.Element {
    const isHighlighted = highlightedFields.includes(field)

    if (!isHighlighted) {
        return <div className={className}>{children}</div>
    }

    return (
        <Tooltip
            title={
                <div className="flex items-center gap-2">
                    <span>Set by template</span>
                    <span className="text-muted-alt text-xs">Click to dismiss</span>
                </div>
            }
            visible={true}
            placement="top"
            interactive
        >
            <div
                className={`cursor-pointer ${className}`}
                onClick={() => onClearHighlight?.(field)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        onClearHighlight?.(field)
                    }
                }}
            >
                <div className="relative">
                    {children}
                    <button
                        type="button"
                        className="absolute -top-2 -right-2 bg-accent text-bg-light rounded-full p-0.5 shadow-sm hover:bg-accent-dark transition-colors"
                        onClick={(e) => {
                            e.stopPropagation()
                            onClearHighlight?.(field)
                        }}
                        aria-label="Dismiss template highlight"
                    >
                        <IconX className="text-xs" />
                    </button>
                </div>
            </div>
        </Tooltip>
    )
}

const TEMPLATE_ICONS: Record<string, React.ReactNode> = {
    simple: <IconToggle className="text-2xl" />,
    targeted: <IconPeople className="text-2xl" />,
    multivariate: <IconTestTube className="text-2xl" />,
    'targeted-multivariate': <IconFlask className="text-2xl" />,
}

export function FeatureFlagTemplates(): JSX.Element | null {
    const { featureFlag, featureFlagLoading, templateExpanded, templates } = useValues(featureFlagLogic)
    const { setTemplateExpanded, applyTemplate } = useActions(featureFlagLogic)

    if (!featureFlag) {
        return null
    }

    // Don't allow template application while the flag is still loading
    // to prevent race conditions where the loader overwrites template values
    const isLoading = featureFlagLoading

    return (
        <>
            <div className="mb-4">
                <LemonCollapse
                    // Use a non-matching key instead of null/undefined to force closed state,
                    // because LemonCollapse uses `activeKey ?? localActiveKey` which falls back
                    // to internal state when activeKey is nullish
                    activeKey={templateExpanded ? 'templates' : '__closed__'}
                    onChange={(key) => setTemplateExpanded(key === 'templates')}
                    panels={[
                        {
                            key: 'templates',
                            header: 'Choose a template',
                            content: (
                                <div className="flex gap-3 overflow-x-auto pt-2">
                                    {templates.map((template) => (
                                        <LemonButton
                                            key={template.id}
                                            type="secondary"
                                            onClick={() => applyTemplate(template.id)}
                                            disabledReason={isLoading ? 'Loading flag data…' : undefined}
                                            className="flex-shrink-0 w-36 !h-auto !items-start"
                                        >
                                            <div className="flex flex-col text-left py-1">
                                                <div className="text-muted mb-2">{TEMPLATE_ICONS[template.id]}</div>
                                                <div className="font-semibold text-sm mb-1">{template.name}</div>
                                                <div className="text-xs text-muted whitespace-normal">
                                                    {template.description}
                                                </div>
                                            </div>
                                        </LemonButton>
                                    ))}
                                </div>
                            ),
                        },
                    ]}
                    embedded
                />
            </div>
            {templateExpanded && <h3 className="text-sm font-semibold text-muted mb-2">Or customize your flag</h3>}
        </>
    )
}
