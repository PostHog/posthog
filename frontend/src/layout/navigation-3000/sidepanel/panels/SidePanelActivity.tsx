import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'

export const SidePanelActivity = (): JSX.Element => {
    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader title="Activity" />
            <div className="flex flex-col overflow-y-auto">
                <p>Todo!</p>
            </div>
        </div>
    )
}
