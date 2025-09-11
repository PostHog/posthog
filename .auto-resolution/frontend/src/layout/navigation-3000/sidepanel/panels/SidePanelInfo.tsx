import { capitalizeFirstLetter } from 'lib/utils'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'

export const SidePanelInfo = (): JSX.Element => {
    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader title={`${capitalizeFirstLetter('info')}`} />
            <div className="flex-1 p-3 overflow-y-auto">info panel yooooo</div>
        </div>
    )
}
