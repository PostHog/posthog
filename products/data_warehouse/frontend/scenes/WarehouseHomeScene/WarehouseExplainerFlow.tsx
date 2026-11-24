import { IconArrowRight, IconCode, IconDatabase, IconLive, IconPlug, IconTerminal } from '@posthog/icons'
import { Text } from '@posthog/quill'

function FlowNode({
    icon,
    title,
    detail,
    emphasized = false,
}: {
    icon: JSX.Element
    title: string
    detail?: string
    emphasized?: boolean
}): JSX.Element {
    return (
        <div
            className={
                emphasized
                    ? 'flex min-w-0 items-center gap-2.5 rounded-md border border-[var(--foreground)] px-3 py-3'
                    : 'flex min-w-0 items-center gap-2.5 rounded-md border px-3 py-2'
            }
        >
            <span className="flex shrink-0 text-muted-foreground [&_svg]:size-4" aria-hidden>
                {icon}
            </span>
            <div className="flex min-w-0 flex-col">
                <Text size="sm" weight="semibold" className="truncate" render={<span />}>
                    {title}
                </Text>
                {detail ? (
                    <Text size="xs" variant="muted" className="truncate" render={<span />}>
                        {detail}
                    </Text>
                ) : null}
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
            aria-label="PostHog data and source tables land in the managed warehouse. You query it from the SQL editor or your own tools."
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
                <FlowNode icon={<IconCode />} title="SQL editor and models" />
                <FlowNode icon={<IconTerminal />} title="Your tools" detail="dbt, Metabase, Hex, Python" />
            </div>
        </div>
    )
}
