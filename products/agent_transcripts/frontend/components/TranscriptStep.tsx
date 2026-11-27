import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@posthog/quill'

const STEP_HEADING_LEVEL = 2

export interface TranscriptStepProps {
    number: number
    title: string
    description: React.ReactNode
    /** The hedgehog for this step, rendered to fill its frame. */
    hog: React.ReactNode
    children: React.ReactNode
}

/** One numbered step of the request: choose the agent, get the transcript, upload it. */
export function TranscriptStep({ number, title, description, hog, children }: TranscriptStepProps): JSX.Element {
    return (
        <Card>
            <CardHeader>
                <CardTitle role="heading" aria-level={STEP_HEADING_LEVEL} className="flex items-center gap-2">
                    <span
                        className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground"
                        aria-hidden
                    >
                        {number}
                    </span>
                    <span>{title}</span>
                </CardTitle>
                <CardDescription>{description}</CardDescription>
                <CardAction className="size-12 @min-[32rem]/agent-transcript:size-16" aria-hidden>
                    {hog}
                </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">{children}</CardContent>
        </Card>
    )
}
