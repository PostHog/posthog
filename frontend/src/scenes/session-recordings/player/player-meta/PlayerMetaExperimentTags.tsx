import { useActions, useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { SessionRecordingSidebarTab } from '~/types'

import { playerSettingsLogic } from '../playerSettingsLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { playerSidebarLogic } from '../sidebar/playerSidebarLogic'
import { sessionRecordingExperimentContextLogic } from './sessionRecordingExperimentContextLogic'

const MAX_VISIBLE_EXPERIMENT_TAGS = 2

export function PlayerMetaExperimentTags(): JSX.Element | null {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { experimentItems, hasExperimentContext } = useValues(
        sessionRecordingExperimentContextLogic({ sessionRecordingId: logicProps.sessionRecordingId })
    )
    const { setTab } = useActions(playerSidebarLogic)
    const { setSidebarOpen } = useActions(playerSettingsLogic)

    if (!hasExperimentContext) {
        return null
    }

    const openOverview = (): void => {
        setSidebarOpen(true)
        setTab(SessionRecordingSidebarTab.OVERVIEW)
    }

    const visibleItems = experimentItems.slice(0, MAX_VISIBLE_EXPERIMENT_TAGS)
    const overflowCount = experimentItems.length - visibleItems.length

    return (
        <span className="flex flex-row items-center gap-x-1 shrink-0" data-attr="replay-experiment-context-chip">
            {visibleItems.map((item) => (
                <Tooltip
                    key={item.experiment_id}
                    title={`This session saw variant "${item.variant}" of ${item.experiment_name}. Flag evaluation — may differ from the experiment's exposure criteria.`}
                >
                    <LemonTag
                        type={item.multiple_variants ? 'warning' : 'default'}
                        onClick={openOverview}
                        forceClickable
                    >
                        🧪 {item.experiment_name}: {item.multiple_variants ? 'saw multiple variants' : item.variant}
                    </LemonTag>
                </Tooltip>
            ))}
            {overflowCount > 0 ? (
                <LemonTag type="default" onClick={openOverview}>
                    +{overflowCount}
                </LemonTag>
            ) : null}
        </span>
    )
}
