import { ReactNode } from 'react'

import { LemonCollapse } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { QuillDisplayTabPanels } from './QuillDisplayTabPanels'

export interface DisplayTabPanel {
    key: string
    header: ReactNode
    content: ReactNode
}

export interface DisplayTabPanelsProps {
    panels: DisplayTabPanel[]
    defaultOpenKeys: string[]
}

export function DisplayTabPanels({ panels, defaultOpenKeys }: DisplayTabPanelsProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillDisplayTabPanels panels={panels} defaultOpenKeys={defaultOpenKeys} />
    }

    return (
        <div className="flex flex-col w-full">
            <LemonCollapse
                embedded
                multiple
                defaultActiveKeys={defaultOpenKeys}
                panels={panels.map((panel) => ({ ...panel, className: 'p-2 flex flex-col gap-2' }))}
            />
        </div>
    )
}
