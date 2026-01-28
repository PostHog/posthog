import { IconChevronDown, IconGear, IconGraph, IconPulse } from '@posthog/icons'
import { LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import { HealthCheck, HealthCheckCategory } from '../healthCheckTypes'
import { HealthCheckItem } from './HealthCheckItem'

interface HealthCheckSectionProps {
    category: HealthCheckCategory
    checks: HealthCheck[]
    defaultOpen?: boolean
    onToggle?: (category: HealthCheckCategory, isExpanded: boolean) => void
}

const CATEGORY_CONFIG: Record<HealthCheckCategory, { title: string; description: string; icon: JSX.Element }> = {
    events: {
        title: 'Event tracking',
        description: 'Events being captured from your site',
        icon: <IconPulse className="w-5 h-5" />,
    },
    configuration: {
        title: 'Configuration',
        description: 'Settings that affect data quality',
        icon: <IconGear className="w-5 h-5" />,
    },
    performance: {
        title: 'Performance',
        description: 'Performance monitoring setup',
        icon: <IconGraph className="w-5 h-5" />,
    },
}

export function HealthCheckSection({
    category,
    checks,
    defaultOpen = true,
    onToggle,
}: HealthCheckSectionProps): JSX.Element {
    const config = CATEGORY_CONFIG[category]
    const passedCount = checks.filter((c) => c.status === 'success').length
    const totalCount = checks.length
    const hasIssues = checks.some((c) => c.status === 'warning' || c.status === 'error')

    const handleChange = (activeKey: HealthCheckCategory | null): void => {
        onToggle?.(category, activeKey === category)
    }

    return (
        <LemonCollapse
            defaultActiveKey={defaultOpen ? category : undefined}
            onChange={handleChange}
            panels={[
                {
                    key: category,
                    header: (
                        <div className="flex items-center justify-between w-full pr-2">
                            <div className="flex items-center gap-3">
                                <div className="text-secondary">{config.icon}</div>
                                <div>
                                    <div className="font-medium">{config.title}</div>
                                    <div className="text-xs text-muted">{config.description}</div>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <LemonTag type={hasIssues ? 'warning' : 'success'} size="small">
                                    {passedCount}/{totalCount} passed
                                </LemonTag>
                                <IconChevronDown className="w-4 h-4 text-muted transition-transform ui-open:rotate-180" />
                            </div>
                        </div>
                    ),
                    content: (
                        <div className="flex flex-col gap-2 pt-2">
                            {checks.map((check) => (
                                <HealthCheckItem key={check.id} check={check} />
                            ))}
                        </div>
                    ),
                },
            ]}
        />
    )
}
