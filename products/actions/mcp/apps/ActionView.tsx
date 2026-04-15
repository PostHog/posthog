import type { ReactElement } from 'react'

import { Badge, Card, DescriptionList, formatDate, Stack } from '@posthog/mosaic'

export interface ActionStepData {
    event?: string | null
    tag_name?: string | null
    text?: string | null
    text_matching?: string | null
    href?: string | null
    href_matching?: string | null
    selector?: string | null
    url?: string | null
    url_matching?: string | null
    properties?: Array<{ key: string; value: unknown; operator?: string; type?: string }>
}

export interface ActionData {
    id: number
    name: string
    description?: string | null
    steps?: ActionStepData[]
    tags?: string[]
    pinned_at?: string | null
    created_at?: string
    created_by?: { first_name?: string; email?: string } | null
    _posthogUrl?: string
}

export interface ActionViewProps {
    action: ActionData
}

function ActionStep({ step, index }: { step: ActionStepData; index: number }): ReactElement {
    const conditions: Array<{ label: string; value: string }> = []
    if (step.event) {
        conditions.push({ label: 'Event', value: step.event })
    }
    if (step.url) {
        conditions.push({ label: `URL ${step.url_matching ?? 'contains'}`, value: step.url })
    }
    if (step.selector) {
        conditions.push({ label: 'Selector', value: step.selector })
    }
    if (step.text) {
        conditions.push({ label: `Text ${step.text_matching ?? 'contains'}`, value: step.text })
    }
    if (step.href) {
        conditions.push({ label: `Link ${step.href_matching ?? 'contains'}`, value: step.href })
    }

    return (
        <Stack gap="xs">
            <span className="text-xs font-medium text-text-secondary uppercase tracking-wide">Step {index + 1}</span>
            {conditions.length > 0 ? (
                <DescriptionList items={conditions.map((c) => ({ label: c.label, value: c.value }))} />
            ) : (
                <span className="text-xs text-text-secondary">No conditions</span>
            )}
        </Stack>
    )
}

export function ActionView({ action }: ActionViewProps): ReactElement {
    return (
        <div className="p-4">
            <Stack gap="md">
                <Stack gap="xs">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold text-text-primary">{action.name}</span>
                        {action.pinned_at && (
                            <Badge variant="info" size="sm">
                                Pinned
                            </Badge>
                        )}
                    </div>
                    {action.description && <span className="text-sm text-text-secondary">{action.description}</span>}
                    {action.tags && action.tags.length > 0 && (
                        <div className="flex gap-1 flex-wrap">
                            {action.tags.map((tag) => (
                                <Badge key={tag} variant="neutral" size="sm">
                                    {tag}
                                </Badge>
                            ))}
                        </div>
                    )}
                </Stack>

                <Card padding="md">
                    <DescriptionList
                        items={[
                            ...(action.created_at ? [{ label: 'Created', value: formatDate(action.created_at) }] : []),
                            ...(action.created_by
                                ? [
                                      {
                                          label: 'Created by',
                                          value: action.created_by.first_name || action.created_by.email || 'Unknown',
                                      },
                                  ]
                                : []),
                        ]}
                    />
                </Card>

                {action.steps && action.steps.length > 0 && (
                    <Card padding="md">
                        <Stack gap="md">
                            <span className="text-sm font-semibold text-text-primary">
                                Steps ({action.steps.length})
                            </span>
                            {action.steps.map((step, i) => (
                                <div key={i}>
                                    {i > 0 && <div className="border-t border-border-primary -mx-4 mb-3" />}
                                    <ActionStep step={step} index={i} />
                                </div>
                            ))}
                        </Stack>
                    </Card>
                )}
            </Stack>
        </div>
    )
}
