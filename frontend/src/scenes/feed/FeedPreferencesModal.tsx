import { useActions, useValues } from 'kea'

import {
    IconClock,
    IconComment,
    IconDashboard,
    IconDatabase,
    IconFlag,
    IconFlask,
    IconGraph,
    IconRewindPlay,
} from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { FeedActivityType } from '~/types'

import { feedLogic } from './feedLogic'

function getActivityIcon(type: FeedActivityType): JSX.Element {
    const iconMap: Record<FeedActivityType, JSX.Element> = {
        [FeedActivityType.Dashboard]: <IconDashboard />,
        [FeedActivityType.EventDefinition]: <IconGraph />,
        [FeedActivityType.ExperimentLaunched]: <IconFlask />,
        [FeedActivityType.ExperimentCompleted]: <IconFlask />,
        [FeedActivityType.FeatureFlag]: <IconFlag />,
        [FeedActivityType.Survey]: <IconComment />,
        [FeedActivityType.ReplayPlaylist]: <IconRewindPlay />,
        [FeedActivityType.ExpiringRecordings]: <IconClock />,
        [FeedActivityType.ExternalDataSource]: <IconDatabase />,
    }
    return iconMap[type] || <IconGraph />
}

function getActivityTypeLabel(type: FeedActivityType): string {
    const labels: Record<FeedActivityType, string> = {
        [FeedActivityType.Dashboard]: 'New dashboards',
        [FeedActivityType.EventDefinition]: 'Event definitions',
        [FeedActivityType.ExperimentLaunched]: 'Experiments launched',
        [FeedActivityType.ExperimentCompleted]: 'Experiments completed',
        [FeedActivityType.ExternalDataSource]: 'Data connections',
        [FeedActivityType.FeatureFlag]: 'Feature flags',
        [FeedActivityType.Survey]: 'Surveys',
        [FeedActivityType.ReplayPlaylist]: 'Replay playlists',
        [FeedActivityType.ExpiringRecordings]: 'Expiring recordings',
    }
    return labels[type] || type
}

export function FeedPreferencesModal(): JSX.Element {
    const { preferences, preferencesModalOpen } = useValues(feedLogic)
    const { closePreferencesModal, toggleActivityType, updatePreferences } = useActions(feedLogic)

    if (!preferences) {
        return <></>
    }

    return (
        <LemonModal
            isOpen={preferencesModalOpen}
            onClose={closePreferencesModal}
            title="Feed preferences"
            description="Choose which activity types appear in your feed"
            footer={
                <div className="flex justify-between items-center w-full">
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() =>
                                updatePreferences({
                                    enabled_types: Object.fromEntries(
                                        Object.values(FeedActivityType).map((type) => [type, true])
                                    ),
                                })
                            }
                        >
                            Enable all
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            onClick={() =>
                                updatePreferences({
                                    enabled_types: Object.fromEntries(
                                        Object.values(FeedActivityType).map((type) => [type, false])
                                    ),
                                })
                            }
                        >
                            Disable all
                        </LemonButton>
                    </div>
                    <LemonButton type="primary" onClick={closePreferencesModal}>
                        Done
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-2">
                {Object.values(FeedActivityType).map((type) => (
                    <LemonCheckbox
                        key={type}
                        checked={preferences.enabled_types[type] ?? true}
                        onChange={() => toggleActivityType(type)}
                        label={
                            <div className="flex items-center gap-2">
                                {getActivityIcon(type)}
                                <span>{getActivityTypeLabel(type)}</span>
                            </div>
                        }
                    />
                ))}
            </div>
        </LemonModal>
    )
}
