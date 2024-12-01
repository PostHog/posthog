import clsx from 'clsx'

export function PanelsUI(): JSX.Element {
    return (
        <PanelContainer className="SessionRecordings__panel-layout">
            <PanelContainer className="flex-col">
                <Panel className="bg-[red]">
                    <>Filters</>
                </Panel>
                <Panel priority className="bg-[yellow] min-w-[250px]">
                    <>Playlist</>
                </Panel>
            </PanelContainer>

            <PanelContainer priority className="PanelLayout__right h-full overflow-y-auto min-w-[300px]">
                <Panel priority className="bg-[green] border border-8 border-[blue] min-w-[300px] min-h-[300px]">
                    <>Main content</>
                </Panel>
                <Panel className="PanelLayout__inspector bg-[pink] min-w-[250px] overflow-y-auto">
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
            </PanelContainer>
        </PanelContainer>
    )
}

function PanelContainer({
    children,
    priority,
    className,
}: {
    children: React.ReactNode
    priority?: boolean
    className?: string
}): JSX.Element {
    return (
        <div className={clsx('flex gap-2 flex-wrap', priority ? 'flex-[10]' : 'grow basis-0', className)}>
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
