import { IconPlus } from '@posthog/icons'
import { Button, Heading, ItemGroup, Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

interface QuillAccessSectionProps {
    title: string
    onAddClick: () => void
    addDisabledReason?: string
    /** Feeds the add button's data-attr, e.g. "member" → `access-control-add-member`. */
    subject: 'member' | 'role'
    loading: boolean
    emptyText: string
    children: React.ReactNode[]
}

export function QuillAccessSection({
    title,
    onAddClick,
    addDisabledReason,
    subject,
    loading,
    emptyText,
    children,
}: QuillAccessSectionProps): JSX.Element {
    return (
        <section className="flex flex-col gap-1">
            <div className="flex items-center justify-between gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    {title}
                </Heading>
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="outline"
                                disabled={!!addDisabledReason}
                                onClick={onAddClick}
                                data-attr={`access-control-add-${subject}`}
                            />
                        }
                    >
                        <IconPlus />
                        Add
                    </TooltipTrigger>
                    {addDisabledReason && <TooltipContent>{addDisabledReason}</TooltipContent>}
                </Tooltip>
            </div>
            {loading && !children.length ? (
                <div className="flex flex-col gap-1">
                    <Skeleton className="h-11" />
                    <Skeleton className="h-11 opacity-70" />
                </div>
            ) : !children.length ? (
                <Text size="xs" variant="muted">
                    {emptyText}
                </Text>
            ) : (
                <ItemGroup combined>{children}</ItemGroup>
            )}
        </section>
    )
}
