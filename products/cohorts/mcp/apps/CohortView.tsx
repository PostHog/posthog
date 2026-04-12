import type { ReactElement } from 'react'

import { Badge, Card, DescriptionList, formatDate, Stack } from '@posthog/mosaic'

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
            <Stack gap="md">
                <Stack gap="xs">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold text-text-primary">{cohort.name}</span>
                        <Badge variant={cohort.is_static ? 'neutral' : 'info'} size="md">
                            {cohort.is_static ? 'Static' : 'Dynamic'}
                        </Badge>
                        {cohort.is_calculating && (
                            <Badge variant="warning" size="sm">
                                Calculating...
                            </Badge>
                        )}
                    </div>
                    {cohort.description && <span className="text-sm text-text-secondary">{cohort.description}</span>}
                </Stack>

                <Card padding="md">
                    <DescriptionList
                        columns={2}
                        items={[
                            ...(cohort.count != null
                                ? [{ label: 'Persons', value: cohort.count.toLocaleString() }]
                                : []),
                            ...(cohort.created_at ? [{ label: 'Created', value: formatDate(cohort.created_at) }] : []),
                            ...(cohort.created_by
                                ? [
                                      {
                                          label: 'Created by',
                                          value: cohort.created_by.first_name || cohort.created_by.email || 'Unknown',
                                      },
                                  ]
                                : []),
                        ]}
                    />
                </Card>
            </Stack>
        </div>
    )
}
