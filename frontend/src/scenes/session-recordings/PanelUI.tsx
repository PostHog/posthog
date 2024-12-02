import './SessionReplay.scss'

import clsx from 'clsx'

export function PanelsUI(): JSX.Element {
    return (
        <PanelLayout className="SessionReplay__layout">
            <PanelContainer primary={false} className="PanelLayout__secondary flex-col">
                <Panel primary={false} className="bg-[red]">
                    <>Filters</>
                </Panel>
                <Panel primary className="PanelLayout__playlist bg-[yellow]">
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

            <PanelContainer primary={true} className="PanelLayout__primary">
                <Panel primary className="PanelLayout__playback bg-[green] border border-8 border-[blue]">
                    <>Main content</>
                </Panel>
                <Panel primary={false} className="PanelLayout__inspector bg-[pink]">
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
        </PanelLayout>
    )
}

function PanelLayout(props: Omit<PanelContainerProps, 'primary'>): JSX.Element {
    return <PanelContainer {...props} primary={false} />
}

type PanelContainerProps = {
    children: React.ReactNode
    primary: boolean
    className?: string
}

function PanelContainer({ children, primary, className }: PanelContainerProps): JSX.Element {
    return <div className={clsx('flex flex-wrap gap-2', primary && 'flex-1', className)}>{children}</div>
}

function Panel({
    className,
    primary,
    children,
}: {
    className?: string
    primary: boolean
    children: JSX.Element
}): JSX.Element {
    return (
        <div className={clsx(className, primary && 'flex-1')}>
            <div>Header</div>
            {children}
        </div>
    )
}
