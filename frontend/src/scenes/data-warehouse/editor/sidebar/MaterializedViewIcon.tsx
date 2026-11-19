import { IconDatabase, IconDocument, IconEndpoints } from '@posthog/icons'

function MaterializedBadgedIcon({ children }: { children: JSX.Element }): JSX.Element {
    return (
        <span className="relative flex">
            {children}
            <span className="absolute -bottom-0.5 -right-1 flex size-3 items-center justify-center rounded-full bg-sky-500 text-white [&_svg]:size-2">
                <IconDatabase />
            </span>
        </span>
    )
}

export function MaterializedViewIcon(): JSX.Element {
    return (
        <MaterializedBadgedIcon>
            <IconDocument className="text-sky-500" />
        </MaterializedBadgedIcon>
    )
}

export function MaterializedEndpointIcon(): JSX.Element {
    return (
        <MaterializedBadgedIcon>
            <IconEndpoints className="text-sky-500" />
        </MaterializedBadgedIcon>
    )
}
