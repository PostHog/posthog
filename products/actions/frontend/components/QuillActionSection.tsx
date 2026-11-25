import { Collapsible, CollapsibleContent, CollapsibleHeader, CollapsibleTrigger, Text } from '@posthog/quill'

/** One section of the action page: a title and a line of description, with a chevron that opens and closes it. */
export function QuillActionSection({
    title,
    description,
    children,
}: {
    title: string
    description: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <Collapsible defaultOpen className="rounded-md border border-border p-2">
            <CollapsibleHeader>
                <CollapsibleTrigger iconOnly>{`Toggle ${title.toLowerCase()}`}</CollapsibleTrigger>
                <div className="flex min-w-0 flex-col gap-0.5 py-1">
                    <Text size="sm" weight="semibold" render={<span className="m-0" />}>
                        {title}
                    </Text>
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        {description}
                    </Text>
                </div>
            </CollapsibleHeader>
            <CollapsibleContent className="flex flex-col gap-2 p-2">{children}</CollapsibleContent>
        </Collapsible>
    )
}
