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
    created_by?: { first_name?: string; email?: string } | null
    filters?: Record<string, unknown>
    _posthogUrl?: string
}

export interface CohortViewProps {
    cohort: CohortData
}

export function CohortView({ cohort }: CohortViewProps): ReactElement {
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
                                ...(cohort.created_by
                                    ? [
                                          {
                                              label: 'Created by',
                                              value:
                                                  cohort.created_by.first_name || cohort.created_by.email || 'Unknown',
                                          },
                                      ]
                                    : []),
                            ]}
                        />
                    </CardContent>
                </Card>
            </div>
        </div>
    )
}
