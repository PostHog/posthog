import { PersonDisplay } from '@posthog/apps-common'
import { IconInfo } from '@posthog/icons'
import { useValues } from 'kea'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PlayerSidebarSessionSummary } from 'scenes/session-recordings/player/sidebar/PlayerSidebarSessionSummary'

import { PropertyDefinitionType } from '~/types'

import { playerMetaLogic } from '../playerMetaLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarOverviewGrid } from './PlayerSidebarOverviewGrid'

export function PlayerSidebarOverviewTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson, sessionPlayerMetaDataLoading } = useValues(playerMetaLogic(logicProps))

    return (
        <div className="flex flex-col overflow-auto bg-bg-3000">
            <PlayerSidebarOverviewGrid />
            <PlayerSidebarSessionSummary />
            <div className="font-bold bg-bg-light px-2 border-b py-3">
                <Tooltip title="These are the person properties right now. They might have changed and not match the person properties at the time of recording.">
                    <h2>
                        Latest person properties <IconInfo />
                    </h2>
                </Tooltip>
                <PersonDisplay person={sessionPerson} withIcon noPopover />
            </div>
            {sessionPlayerMetaDataLoading ? (
                <div className="space-y-2">
                    <LemonSkeleton.Row repeat={60} fade={true} className="h-3 w-full" />
                </div>
            ) : (
                <PropertiesTable
                    properties={sessionPerson?.properties || []}
                    type={PropertyDefinitionType.Person}
                    sortProperties
                    embedded
                    filterable
                    className="mt-4"
                />
            )}
        </div>
    )
}
