import { IconArrowRight, IconCode, IconDatabase, IconLive, IconPlug, IconTerminal } from '@posthog/icons'
import { Badge, Text } from '@posthog/quill'

// The PostHog features that read from the warehouse, as the Warehouse sidebar names them.
const POSTHOG_FEATURES = ['SQL editor', 'Models', 'Data catalog']

function FlowNode({
    icon,
    title,
    detail,
    emphasized = false,
    children,
}: {
    icon: JSX.Element
    title: string
    /** One muted line under the title. It wraps, so keep it short. */
    detail?: string
    emphasized?: boolean
    /** Extra content under the title, such as a row of feature names. */
    children?: React.ReactNode
}): JSX.Element {
    return (
        <div
            className={
                emphasized
                    ? 'flex min-w-0 items-start gap-2.5 rounded-md border border-[var(--foreground)] px-3 py-3'
                    : 'flex min-w-0 items-start gap-2.5 rounded-md border px-3 py-2'
            }
        >
            <span className="mt-0.5 flex shrink-0 text-muted-foreground [&_svg]:size-4" aria-hidden>
                {icon}
            </span>
            <div className="flex min-w-0 flex-col gap-0.5">
                <Text size="sm" weight="semibold" render={<span />}>
                    {title}
                </Text>
                {detail ? (
                    <Text size="xs" variant="muted" render={<span />}>
                        {detail}
                    </Text>
                ) : null}
                {children}
            </div>
        </div>
    )
}

// The arrow points down while the columns are stacked, and right once they sit side by side.
function FlowArrow(): JSX.Element {
    return (
        <span
            className="flex shrink-0 justify-center text-muted-foreground [&_svg]:size-4 [&_svg]:rotate-90 @2xl/warehouse-home:[&_svg]:rotate-0"
            aria-hidden
        >
            <IconArrowRight />
        </span>
    )
}

/** How data moves: PostHog data and sources go into the warehouse, and queries come out of it. */
export function WarehouseExplainerFlow(): JSX.Element {
    return (
        <div
            role="img"
            aria-label={`PostHog data and source tables land in the managed warehouse. You use it in PostHog through ${POSTHOG_FEATURES.join(', ')}, or from your own tools through a Trino-compatible connection.`}
            className="grid items-center gap-3 @2xl/warehouse-home:grid-cols-[1fr_auto_1fr_auto_1fr]"
            data-attr="warehouse-explainer-flow"
        >
            <div className="flex flex-col gap-2">
                <FlowNode icon={<IconLive />} title="PostHog data" detail="Events and persons" />
                <FlowNode icon={<IconPlug />} title="Sources" detail="Tables from each sync" />
            </div>
            <FlowArrow />
            <FlowNode
                icon={<IconDatabase />}
                title="Managed warehouse"
                detail="Shared by your organization"
                emphasized
            />
            <FlowArrow />
            <div className="flex flex-col gap-2">
                <FlowNode icon={<IconCode />} title="In PostHog">
                    <div className="mt-1 flex flex-wrap gap-1">
                        {POSTHOG_FEATURES.map((feature) => (
                            <Badge key={feature} variant="default">
                                {feature}
                            </Badge>
                        ))}
                    </div>
                </FlowNode>
                <FlowNode
                    icon={<IconTerminal />}
                    title="In your own tools"
                    detail="You get a Trino-compatible connection for dbt, Metabase, Hex, Python and more."
                />
            </div>
        </div>
    )
}
