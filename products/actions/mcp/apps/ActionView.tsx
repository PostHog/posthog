import type { ReactElement } from 'react'

import { DescriptionList, formatDate } from '@posthog/mcp-ui'
import { Badge, Card, CardContent } from '@posthog/quill'

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
        <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Step {index + 1}</span>
            {conditions.length > 0 ? (
                <DescriptionList items={conditions.map((c) => ({ label: c.label, value: c.value }))} />
            ) : (
                <span className="text-xs text-muted-foreground">No conditions</span>
            )}
        </div>
    )
}

export function ActionView({ action }: ActionViewProps): ReactElement {
    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold">{action.name}</span>
                        {action.pinned_at && <Badge variant="info">Pinned</Badge>}
                    </div>
                    {action.description && <span className="text-sm text-muted-foreground">{action.description}</span>}
                    {action.tags && action.tags.length > 0 && (
                        <div className="flex gap-1 flex-wrap">
                            {action.tags.map((tag) => (
                                <Badge key={tag}>{tag}</Badge>
                            ))}
                        </div>
                    )}
                </div>

                <Card>
                    <CardContent>
                        <DescriptionList
                            items={[
                                ...(action.created_at
                                    ? [{ label: 'Created', value: formatDate(action.created_at) }]
                                    : []),
                                ...(action.created_by
                                    ? [
                                          {
                                              label: 'Created by',
                                              value:
                                                  action.created_by.first_name || action.created_by.email || 'Unknown',
                                          },
                                      ]
                                    : []),
                            ]}
                        />
                    </CardContent>
                </Card>

                {action.steps && action.steps.length > 0 && (
                    <Card>
                        <CardContent>
                            <div className="flex flex-col gap-3">
                                <span className="text-sm font-semibold">Steps ({action.steps.length})</span>
                                {action.steps.map((step, i) => (
                                    <div key={i}>
                                        {i > 0 && <div className="border-t -mx-4 mb-3" />}
                                        <ActionStep step={step} index={i} />
                                    </div>
                                ))}
                            </div>
                        </CardContent>
                    </Card>
                )}
            </div>
        </div>
    )
}
