import clsx from 'clsx'

export function PanelsUI(): JSX.Element {
    return (
        <Container className="max-h-[615px] h-[615px]">
            <Container column>
                <Panel className="bg-[red]">
                    <>Filters</>
                </Panel>
                <Panel priority className="bg-[yellow] min-w-[250px]">
                    <>Playlist</>
                </Panel>
            </Container>

            <Container priority className="h-full overflow-y-auto min-w-[300px]">
                <Panel priority className="bg-[green] border border-8 border-[blue] min-w-[300px] h-full">
                    <>Main content</>
                </Panel>
                <Panel className="bg-[pink] min-w-[250px] overflow-y-auto">
                    <div className="flex flex-col">
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                        <div>Content</div>
                    </div>
                </Panel>
            </Container>
        </Container>
    )
}

function Container({
    children,
    column,
    priority,
    className,
}: {
    children: React.ReactNode
    column?: boolean
    priority?: boolean
    className?: string
}): JSX.Element {
    return (
        <div
            className={clsx(
                'flex gap-2 flex-wrap',
                column && 'flex-col',
                priority ? 'flex-[10]' : 'grow basis-0',
                className
            )}
        >
            {children}
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
    priority?: boolean
}): JSX.Element {
    return (
        <div className={clsx('h-full', className, priority ? 'flex-[10]' : 'flex-1')}>
            <div>Header</div>
            {children}
        </div>
    )
}
