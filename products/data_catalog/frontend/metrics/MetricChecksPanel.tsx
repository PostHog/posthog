import { Badge, Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import {
    CHECK_STATUS_TAG_TYPES,
    CHECK_TYPE_LABELS,
    byStatusAttention,
} from 'products/data_quality/frontend/checksConstants'
import type { SubjectGroup } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import type { DataCatalogMetricApi } from '../generated/api.schemas'

const STATUS_BADGE_VARIANTS: Partial<Record<LemonTagType, 'success' | 'destructive' | 'warning' | 'default'>> = {
    success: 'success',
    danger: 'destructive',
    warning: 'warning',
}

interface MetricChecksPanelProps {
    metric: DataCatalogMetricApi
    group: SubjectGroup
}

export function MetricChecksPanel({ metric, group }: MetricChecksPanelProps): JSX.Element {
    const checks = [...group.checks].sort((left, right) =>
        byStatusAttention({ status: left.last_status }, { status: right.last_status })
    )

    return (
        <div className="flex flex-col gap-2 py-2" data-attr="data-catalog-metrics-checks-panel">
            <Table size="sm" fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead expand>Check</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Last run</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {checks.map((check) => (
                        <TableRow key={check.id}>
                            <TableCell expand>
                                <Text size="xs">{check.name || CHECK_TYPE_LABELS[check.check_type]}</Text>
                            </TableCell>
                            <TableCell>
                                {check.last_status ? (
                                    <Badge
                                        variant={
                                            STATUS_BADGE_VARIANTS[CHECK_STATUS_TAG_TYPES[check.last_status]] ??
                                            'default'
                                        }
                                    >
                                        {capitalizeFirstLetter(check.last_status)}
                                    </Badge>
                                ) : (
                                    <Text size="xs" variant="muted">
                                        Not run yet
                                    </Text>
                                )}
                            </TableCell>
                            <TableCell className="whitespace-nowrap">
                                <Text size="xs" variant="muted">
                                    {check.last_run_at ? <TZLabel time={check.last_run_at} /> : 'Never'}
                                </Text>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
            <Button
                variant="link"
                size="inline"
                className="self-start px-2"
                render={<LinkPrimitive to={urls.dataCatalogMetric(metric.name, 'data-quality')} />}
                data-attr="data-catalog-metrics-open-data-quality"
            >
                Open data quality
            </Button>
        </div>
    )
}
