import { useValues } from 'kea'

import { Skeleton } from '@posthog/quill'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { asDisplay, pickBestPersonDistinctId } from 'products/persons/frontend/person-utils'

import { QuillOverviewRow } from './QuillOverviewRow'
import { QuillOverviewRows } from './QuillOverviewRows'

export function QuillOverviewPersonCard(): JSX.Element {
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
            <div className="rounded border border-border bg-card px-2 py-1.5 flex flex-col justify-center min-w-0">
                {loading ? (
                    <>
                        <Skeleton className="h-4 mb-1" />
                        <Skeleton className="h-4" />
                    </>
                ) : (
                    <>
                        <CopyToClipboardInline
                            description="person"
                            explicitValue={displayName}
                            className="font-semibold max-w-full"
                            data-attr="replay-overview-copy-person"
                        >
                            <span className="truncate">{displayName}</span>
                        </CopyToClipboardInline>
                        {distinctId && (
                            <CopyToClipboardInline
                                description="distinct ID"
                                explicitValue={distinctId}
                                className="text-xs text-muted-foreground font-mono max-w-full"
                                data-attr="replay-overview-copy-distinct-id"
                            >
                                <span className="truncate">{distinctId}</span>
                            </CopyToClipboardInline>
                        )}
                    </>
                )}
            </div>
            <QuillOverviewRows
                items={overviewItemsByTab.person}
                pickerGroupType={TaxonomicFilterGroupType.PersonProperties}
                leadingRows={
                    <>
                        {name && (
                            <QuillOverviewRow label="Name" valueTooltip={name}>
                                <span className="font-medium truncate">{name}</span>
                            </QuillOverviewRow>
                        )}
                        {sessionPerson?.created_at && (
                            <QuillOverviewRow
                                label="First seen"
                                valueTooltip="When this person was first seen in your project"
                            >
                                <span className="font-medium">
                                    <TZLabel time={sessionPerson.created_at} />
                                </span>
                            </QuillOverviewRow>
                        )}
                    </>
                }
            />
        </>
    )
}
