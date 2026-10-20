import { useValues } from 'kea'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { asDisplay, pickBestPersonDistinctId } from 'products/persons/frontend/person-utils'

import { OverviewGridItem } from '../../components/OverviewGrid'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { PlayerSidebarOverviewRows } from './PlayerSidebarOverviewRows'

export function PlayerSidebarOverviewPersonTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { overviewItemsByTab, sessionPerson, loading } = useValues(playerMetaLogic(logicProps))

    const distinctId = pickBestPersonDistinctId(sessionPerson?.distinct_ids)
    const displayName = asDisplay(sessionPerson)
    const name =
        typeof sessionPerson?.properties?.name === 'string' && sessionPerson.properties.name !== displayName
            ? sessionPerson.properties.name
            : null

    return (
        <>
            <div className="rounded border bg-surface-primary px-2 py-1.5 flex flex-col min-w-0">
                {loading ? (
                    <LemonSkeleton.Row repeat={2} className="h-4" />
                ) : (
                    <>
                        <span className="font-semibold truncate">{displayName}</span>
                        {distinctId && (
                            <CopyToClipboardInline
                                description="distinct ID"
                                className="text-xs text-secondary font-mono truncate"
                                data-attr="replay-overview-copy-distinct-id"
                            >
                                {distinctId}
                            </CopyToClipboardInline>
                        )}
                    </>
                )}
            </div>
            <PlayerSidebarOverviewRows
                items={overviewItemsByTab.person}
                pickerGroupType={TaxonomicFilterGroupType.PersonProperties}
                leadingRows={
                    <>
                        {name && (
                            <div className="px-2 py-1">
                                <OverviewGridItem label="Name" description={name} fadeLabel>
                                    <span className="font-medium truncate">{name}</span>
                                </OverviewGridItem>
                            </div>
                        )}
                        {sessionPerson?.created_at && (
                            <div className="px-2 py-1">
                                <OverviewGridItem
                                    label="First seen"
                                    description="When this person was first seen in your project"
                                    fadeLabel
                                >
                                    <span className="font-medium">
                                        <TZLabel time={sessionPerson.created_at} />
                                    </span>
                                </OverviewGridItem>
                            </div>
                        )}
                    </>
                }
            />
        </>
    )
}
