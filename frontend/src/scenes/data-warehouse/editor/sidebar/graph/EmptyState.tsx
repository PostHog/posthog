import { IconArchive } from '@posthog/icons'

export function EmptyState({ heading, detail }: { heading: string; detail: string }): JSX.Element {
    return (
        <div
            data-attr="upstream-graph-empty-state"
            className="flex flex-col flex-1 rounded p-4 w-full items-center justify-center"
        >
            <IconArchive className="text-5xl mb-2 text-tertiary" />
            <h2 className="text-xl leading-tight">{heading}</h2>
            <p className="text-sm text-center text-balance text-tertiary">{detail}</p>
        </div>
    )
}
