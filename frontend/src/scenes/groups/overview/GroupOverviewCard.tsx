import './GroupOverviewCard.scss'

type GroupOverviewCardProps = {
    title: string
    children: React.ReactNode
}

export function GroupOverviewCard({ title, children }: GroupOverviewCardProps): JSX.Element {
    return (
        <div className="GroupOverviewCard">
            <div className="GroupOverviewCardMeta">
                <div className="GroupOverviewCardMeta__primary">
                    <h4>{title}</h4>
                </div>
                <hr className="m-0" />
            </div>
            <div className="GroupOverviewCardContent">{children}</div>
        </div>
    )
}
