import { Heading, Text } from '@posthog/quill'

export function StepLayout({
    title,
    description,
    children,
    primary,
}: {
    title: string
    description?: React.ReactNode
    children?: React.ReactNode
    /** Steps that advance on selection leave this out. */
    primary?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-6">
            <div className="flex flex-col gap-1">
                <Heading size="xl" render={<h1 />}>
                    {title}
                </Heading>
                {description && <Text variant="muted">{description}</Text>}
            </div>
            {children}
            {primary && <div className="flex">{primary}</div>}
        </div>
    )
}
