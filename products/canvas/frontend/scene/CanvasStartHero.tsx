import { IconPalette } from '@posthog/icons'
import { EmptyMedia, Heading, Text } from '@posthog/quill'

/** The centered start of a canvas with nothing in it yet, like PostHog Desktop: a heading, a line of help, and the composer. */
export function CanvasStartHero({
    description,
    children,
}: {
    description: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex h-full w-full flex-col items-center overflow-y-auto px-4 py-10">
            <div className="my-auto flex w-full max-w-2xl flex-col gap-5">
                <div className="flex flex-col items-center gap-2 text-center">
                    <EmptyMedia variant="icon">
                        <IconPalette />
                    </EmptyMedia>
                    <Heading render={<h1 />} size="xl">
                        Build a canvas
                    </Heading>
                    <Text size="sm" variant="muted">
                        {description}
                    </Text>
                </div>
                {children}
            </div>
        </div>
    )
}
