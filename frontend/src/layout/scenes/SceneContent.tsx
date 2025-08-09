export function SceneContent(): JSX.Element {
    return <div>SceneContent</div>
}

export function SceneMainTitle({
    title,
    description,
}: {
    title: React.ReactNode
    description: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-0">
            <h1 className="text-3xl font-bold my-0">{title}</h1>
            <p className="text-sm text-secondary my-0">{description}</p>
        </div>
    )
}

export function SceneItemEdit(): JSX.Element {
    return <div>SceneEdit</div>
}

export function SceneItemNew({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="flex flex-col gap-8">{children}</div>
}
