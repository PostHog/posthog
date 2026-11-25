import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { useTodayPeopleTitle } from '~/layout/today/todayPeopleRows'
import { ProductKey } from '~/queries/schema/schema-general'

import { ComposeTicketButton } from '../../components/ComposeTicket/ComposeTicketButton'
import { ScenesTabs } from '../../components/ScenesTabs'
import { SupportOverviewCharts } from '../../components/SupportOverviewCharts/SupportOverviewCharts'
import { SupportOverviewNumbers } from '../../components/SupportOverviewNumbers/SupportOverviewNumbers'
import { supportEmptyState } from '../../emptyState/supportEmptyState'
import { supportOverviewSceneLogic } from './supportOverviewSceneLogic'

export const scene: SceneExport = {
    component: SupportOverviewScene,
    logic: supportOverviewSceneLogic,
    productKey: ProductKey.CONVERSATIONS,
    emptyState: supportEmptyState,
}

export function SupportOverviewScene(): JSX.Element {
    const supportTitle = useTodayPeopleTitle('support')

    return (
        <SceneContent className="pb-4">
            <SceneTitleSection
                name={supportTitle?.name ?? 'Support'}
                description=""
                resourceType={supportTitle?.resourceType ?? { type: 'conversation' }}
                actions={<ComposeTicketButton />}
            />
            <ScenesTabs />
            <SupportOverviewNumbers />
            <SupportOverviewCharts />
        </SceneContent>
    )
}
