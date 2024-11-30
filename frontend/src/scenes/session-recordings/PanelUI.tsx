import clsx from 'clsx'

export function PanelsUI(): JSX.Element {
    return (
        <Container column className="max-h-[350px]">
            <Container>
                <Panel className="bg-[red]">
                    <>Filters</>
                </Panel>
            </Container>
            <Container wrap priority className="min-h-0">
                <Container wrap>
                    <Panel className="bg-[yellow] min-w-[250px]">
                        <>Playlist</>
                    </Panel>
                </Container>

                <Container wrap priority className="min-h-0">
                    <Panel priority className="bg-[green] border border-8 border-[blue] min-w-[300px]">
                        <>Main content</>
                    </Panel>
                    <Panel className="bg-[pink] min-w-[250px] min-h-0 overflow-y-auto">
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
                    </Panel>
                </Container>
            </Container>
        </Container>
    )
}

function Container({
    children,
    column,
    wrap,
    priority,
    className,
}: {
    children: React.ReactNode
    column?: boolean
    wrap?: boolean
    priority?: boolean
    className?: string
}): JSX.Element {
    return (
        <div
            className={clsx(
                'flex gap-2',
                column && 'flex-col',
                wrap && 'flex-wrap',
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
        <div className={clsx(className, priority ? 'flex-[10]' : 'flex-1')}>
            <div>Header</div>
            {children}
        </div>
    )
}
