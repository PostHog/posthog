import { LemonTag, LemonTagType } from '@posthog/lemon-ui'

type TestStatus = 'flaky' | 'passed' | 'failed' | 'skipped' | 'error'

const STATUS_CONFIG: Record<TestStatus, { label: string; type: LemonTagType }> = {
    flaky: { label: 'Flaky', type: 'warning' },
    passed: { label: 'Passed', type: 'success' },
    failed: { label: 'Failed', type: 'danger' },
    skipped: { label: 'Skipped', type: 'muted' },
    error: { label: 'Error', type: 'danger' },
}

interface TestStatusBadgeProps {
    status: string
}

export function TestStatusBadge({ status }: TestStatusBadgeProps): JSX.Element {
    const config = STATUS_CONFIG[status as TestStatus] || { label: status, type: 'default' as LemonTagType }
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}
