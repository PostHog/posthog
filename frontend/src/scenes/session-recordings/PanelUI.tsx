import './SessionReplay.scss'

import clsx from 'clsx'

export function PanelsUI(): JSX.Element {
    return (
        <PanelContainer className="SessionReplay__layout">
            <PanelContainer className="PanelLayout__secondary flex-col">
                <Panel className="bg-[red]">
                    <>Filters</>
                </Panel>
                <Panel className="PanelLayout__playlist bg-[yellow]">
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
                    </div>
                </Panel>
            </PanelContainer>

            <PanelContainer className="PanelLayout__primary" tempClassName="">
                <Panel className="PanelLayout__playback bg-[green] border border-8 border-[blue]">
                    <>Main content</>
                </Panel>
                <Panel className="PanelLayout__inspector bg-[pink]" tempClassName="">
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
    className,
    tempClassName,
}: {
    children: React.ReactNode
    className?: string
    tempClassName?: string
}): JSX.Element {
    return <div className={clsx('flex flex-wrap gap-2', className, tempClassName)}>{children}</div>
}

function Panel({
    className,
    children,
    tempClassName,
}: {
    className?: string
    children: JSX.Element
    tempClassName?: string
}): JSX.Element {
    return (
        <div className={clsx(className, tempClassName)}>
            <div>Header</div>
            {children}
        </div>
    )
}
