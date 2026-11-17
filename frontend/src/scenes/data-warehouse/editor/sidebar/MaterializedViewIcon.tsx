import { IconDatabase, IconDocument } from '@posthog/icons'

export function MaterializedViewIcon(): JSX.Element {
    return (
        <span className="relative flex">
            <IconDocument className="text-sky-500" />
            <span className="absolute -bottom-0.5 -right-1 flex size-3 items-center justify-center rounded-full bg-sky-500 text-white [&_svg]:size-2">
                <IconDatabase />
            </span>
        </span>
    )
}
