import { Heading } from '@posthog/quill'

export interface TranscriptHeroProps {
    /** The hedgehog for this state, rendered to fill its frame. */
    hog: React.ReactNode
    title: React.ReactNode
    children?: React.ReactNode
    'data-attr': string
}

/** The top of the transcript page: a hedgehog, the page heading and a few lines about where things stand. */
export function TranscriptHero({ hog, title, children, 'data-attr': dataAttr }: TranscriptHeroProps): JSX.Element {
    return (
        <section className="flex flex-col items-center gap-3 text-center" data-attr={dataAttr}>
            <div className="size-24 @min-[32rem]/agent-transcript:size-32" aria-hidden>
                {hog}
            </div>
            <Heading size="2xl" render={<h1 className="m-0 text-balance" />}>
                {title}
            </Heading>
            {children && <div className="flex max-w-lg flex-col items-center gap-2 text-pretty">{children}</div>}
        </section>
    )
}
