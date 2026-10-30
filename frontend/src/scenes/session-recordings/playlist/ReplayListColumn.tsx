import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import { LemonBadge, LemonSegmentedButton } from '@posthog/lemon-ui'

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

    const options = [
        ...(picksList
            ? [
                  {
                      value: 'picks' as const,
                      label: (
                          <span className="flex items-center gap-1">
                              <span>Highlights</span>
                              {unwatchedPicksCount > 0 && (
                                  <LemonBadge.Number count={unwatchedPicksCount} size="small" status="muted" />
                              )}
                          </span>
                      ),
                      'data-attr': 'list-segment-picks',
                  },
              ]
            : []),
        {
            value: 'recordings' as const,
            label: 'All recordings',
            'data-attr': 'list-segment-recordings',
        },
        ...(collections
            ? [{ value: 'collections' as const, label: 'Collections', 'data-attr': 'list-segment-collections' }]
            : []),
    ]

    return (
        <div className="flex flex-col h-full min-h-0">
            {options.length > 1 && (
                <LemonSegmentedButton
                    size="small"
                    fullWidth
                    className="mb-2"
                    value={segment}
                    onChange={(next: ReplayListSegment) => {
                        setSegment(next)
                        if ((next === 'picks') !== (segment === 'picks')) {
                            onPicksSelected?.(next === 'picks')
                        }
                    }}
                    options={options}
                />
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
