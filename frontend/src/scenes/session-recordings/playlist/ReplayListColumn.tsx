import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import { Badge, Tabs, TabsList, TabsTrigger } from '@posthog/quill'

import { ReplayCollectionsSegment } from './ReplayCollectionsSegment'
import { ReplayListPicksMode, ReplayListSegment, replayListColumnLogic } from './replayListColumnLogic'

export interface ReplayListColumnProps {
    logicKey: string
    recordingsList: ReactNode
    /** The Highlights list, when the picks experiment offers one. */
    picksList?: ReactNode
    picksMode: ReplayListPicksMode
    collections?: boolean
    unwatchedPicksCount?: number
    onPicksSelected?: (selected: boolean) => void
}

export function ReplayListColumn({
    logicKey,
    recordingsList,
    picksList,
    picksMode,
    collections = false,
    unwatchedPicksCount = 0,
    onPicksSelected,
}: ReplayListColumnProps): JSX.Element {
    const logic = replayListColumnLogic({ logicKey })
    const { effectiveSegmentFor } = useValues(logic)
    const { setSegment, settleSegment } = useActions(logic)

    const segment = effectiveSegmentFor(picksMode)
    useEffect(() => {
        settleSegment(picksMode)
    }, [picksMode, settleSegment])

    const options: { value: ReplayListSegment; label: ReactNode; dataAttr: string }[] = [
        ...(picksList
            ? [
                  {
                      value: 'picks' as const,
                      label: (
                          <>
                              Highlights
                              {unwatchedPicksCount > 0 && (
                                  <Badge className="bg-(--primary) text-(--primary-foreground) group-data-active/button:bg-(--primary-foreground) group-data-active/button:text-(--primary)">
                                      {unwatchedPicksCount}
                                  </Badge>
                              )}
                          </>
                      ),
                      dataAttr: 'list-segment-picks',
                  },
              ]
            : []),
        { value: 'recordings' as const, label: 'All recordings', dataAttr: 'list-segment-recordings' },
        ...(collections
            ? [{ value: 'collections' as const, label: 'Collections', dataAttr: 'list-segment-collections' }]
            : []),
    ]

    return (
        <div className="flex flex-col h-full min-h-0">
            {options.length > 1 && (
                <Tabs
                    data-quill
                    value={segment}
                    onValueChange={(value) => {
                        const next = value as ReplayListSegment
                        setSegment(next)
                        if ((next === 'picks') !== (segment === 'picks')) {
                            onPicksSelected?.(next === 'picks')
                        }
                    }}
                    className="mb-2 shrink-0"
                >
                    <TabsList className="w-full [--quill-tabs-active-bg:var(--primary)]">
                        {options.map((option) => (
                            <TabsTrigger
                                key={option.value}
                                value={option.value}
                                className="text-xs data-active:text-(--primary-foreground)"
                                data-attr={option.dataAttr}
                            >
                                {option.label}
                            </TabsTrigger>
                        ))}
                    </TabsList>
                </Tabs>
            )}
            <div className="flex flex-col flex-1 min-h-0">
                {segment === 'picks' ? (
                    picksList
                ) : segment === 'collections' ? (
                    <ReplayCollectionsSegment logicKey={logicKey} />
                ) : (
                    recordingsList
                )}
            </div>
        </div>
    )
}
