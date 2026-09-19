import type { ReactElement } from 'react'

import { DescriptionList, formatDate } from '@posthog/mcp-ui'
import { Badge, Card, CardContent } from '@posthog/quill'

export interface CohortData {
    id: number
    name: string
    description?: string | null
    is_static?: boolean
    is_calculating?: boolean
    count?: number | null
    created_at?: string
    created_by?: { id?: number; first_name?: string; email?: string } | null
    filters?: Record<string, unknown>
    _posthogUrl?: string
}

export interface CohortViewProps {
    cohort: CohortData
}

export function CohortView({ cohort }: CohortViewProps): ReactElement {
    // The MCP response keeps only created_by.id, so the object can be truthy without a displayable name.
    // Show the creator row only when a name or email is present, to avoid a false "Unknown" label.
    const createdBy = cohort.created_by?.first_name || cohort.created_by?.email
    return (
        <div className="p-4">
            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold">{cohort.name}</span>
                        <Badge variant={cohort.is_static ? 'default' : 'info'}>
                            {cohort.is_static ? 'Static' : 'Dynamic'}
                        </Badge>
                        {cohort.is_calculating && <Badge variant="warning">Calculating...</Badge>}
                    </div>
                    {cohort.description && <span className="text-sm text-muted-foreground">{cohort.description}</span>}
                </div>

                <Card>
                    <CardContent>
                        <DescriptionList
                            columns={2}
                            items={[
                                ...(cohort.count != null
                                    ? [{ label: 'Persons', value: cohort.count.toLocaleString() }]
                                    : []),
                                ...(cohort.created_at
                                    ? [{ label: 'Created', value: formatDate(cohort.created_at) }]
                                    : []),
                                ...(createdBy ? [{ label: 'Created by', value: createdBy }] : []),
                            ]}
                        />
                    </CardContent>
                </Card>
            </div>
        </div>
    )
}
