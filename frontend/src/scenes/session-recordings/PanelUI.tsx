import clsx from 'clsx'

export function PanelsUI(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div>
                <Panel className="bg-[red]">
                    <>Filters</>
                </Panel>
            </div>
            <div className="flex gap-2 flex-wrap">
                <div className="flex gap-2 flex-wrap">
                    <Panel className="bg-[yellow] min-w-[250px]">
                        <>Playlist</>
                    </Panel>
                </div>
                <div className="flex gap-2 flex-1 flex-wrap">
                    <Panel priority={1} className="bg-[green] flex-1 min-w-[200px] flex-grow-[2]">
                        <>Main content</>
                    </Panel>
                    <Panel priority={2} className="bg-[pink] min-w-[250px] flex-grow-[1]">
                        <>Inspector</>
                    </Panel>
                </div>
            </div>
        </div>
    )
}

function Panel({
    className,
    children,
    priority,
}: {
    className?: string
    children: JSX.Element
    priority?: number
}): JSX.Element {
    const priorityClass = ''

    return (
        <div className={clsx(className, priorityClass)}>
            <div>Header</div>
            <div>{children}</div>
        </div>
    )
}
