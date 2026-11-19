import { Badge, Heading, Text } from '@posthog/quill'

export interface QuillFeaturePreviewGroupProps {
    title: string
    description: string
    count: number
    children: React.ReactNode
}

export function QuillFeaturePreviewGroup({
    title,
    description,
    count,
    children,
}: QuillFeaturePreviewGroupProps): JSX.Element {
    return (
        <section className="flex flex-col gap-2" aria-label={title}>
            <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                    <Heading size="sm" render={<h3 />} className="m-0">
                        {title}
                    </Heading>
                    <Badge aria-label={`${count} previews`}>{count}</Badge>
                </div>
                <Text size="xs" variant="muted" render={<p />} className="m-0">
                    {description}
                </Text>
            </div>
            {children}
        </section>
    )
}
