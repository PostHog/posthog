import { Badge, Dot } from '@posthog/quill'

const CHECKS = [
    { label: 'Events are arriving', passed: true },
    { label: 'Pageviews have a URL', passed: true },
    { label: 'Sessions are tracked', passed: true },
    { label: 'Web vitals are captured', passed: false },
]

// TODO(2026-11-26): Delete with the kitchen sink fixture, once a product renders its own custom content in a dashboard.
export function HealthChecklist(): JSX.Element {
    const passed = CHECKS.filter((check) => check.passed).length
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <span className="font-semibold">Setup checks</span>
                <Badge variant={passed === CHECKS.length ? 'success' : 'warning'}>
                    {passed} of {CHECKS.length} passed
                </Badge>
            </div>
            {CHECKS.map(({ label, passed }) => (
                <div key={label} className="flex items-center gap-2">
                    <Dot variant={passed ? 'success' : 'warning'} />
                    <span className={passed ? 'text-secondary' : undefined}>{label}</span>
                </div>
            ))}
        </div>
    )
}
