import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonCollapse } from '@posthog/lemon-ui'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { RecordingOverviewPanels } from './RecordingOverviewPanels'

export function RecordingOverviewDisclosure({ actions }: { actions?: ReactNode }): JSX.Element {
    const { watchPanelOpenSections } = useValues(playerSettingsLogic)
    const { toggleWatchPanelSection } = useActions(playerSettingsLogic)
    const open = watchPanelOpenSections.includes('overview')

    return (
        <div className="relative">
            <LemonCollapse
                size="small"
                panels={[
                    {
                        key: 'overview',
                        header: 'Overview',
                        content: <RecordingOverviewPanels />,
                        dataAttr: 'watch-panel-section-overview',
                    },
                ]}
                activeKey={open ? 'overview' : null}
                onChange={() => toggleWatchPanelSection('overview')}
            />
            {actions && (
                // Height of a small LemonButton, which is what the collapse header renders as.
                <div className="absolute right-1 top-0 h-[2.0625rem] max-w-[70%] flex items-center gap-2">
                    {actions}
                </div>
            )}
        </div>
    )
}
