import React, { CSSProperties, ReactNode, useState } from 'react'
import { ExpandableConfig } from 'lib/components/LemonTable'
import { RowStatus } from 'scenes/session-recordings/player/list/listLogic'
import clsx from 'clsx'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconEllipsis, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { IconWindow } from 'scenes/session-recordings/player/icons'

export interface PlayerListRowProps<T extends Record<string, any>> {
    record: T
    recordIndex: number
    expandable: ExpandableConfig<T> | undefined
    style: CSSProperties | undefined
    keyDetermined: string | null | undefined
    classNameDetermined: string | null | undefined
    statusDetermined: RowStatus | null | undefined
    /** If row is current, row will be highlighted with border and prominent ribbon */
    currentDetermined: boolean
    contentDetermined: ReactNode
    sideContentDetermined: ReactNode
    onClick: (record: T) => void
}

function PlayerListRowRaw<T extends Record<string, any>>({
    record,
    recordIndex,
    expandable,
    style,
    keyDetermined,
    classNameDetermined,
    statusDetermined,
    currentDetermined,
    contentDetermined,
    sideContentDetermined,
    onClick,
}: PlayerListRowProps<T>): JSX.Element {
    const [isRowExpandedLocal, setIsRowExpanded] = useState(false)
    const rowExpandable: number = Number(
        !!expandable && (!expandable.rowExpandable || expandable.rowExpandable(record))
    )
    const isRowExpanded =
        !expandable?.isRowExpanded || expandable?.isRowExpanded?.(record) === -1
            ? isRowExpandedLocal
            : !!expandable?.isRowExpanded?.(record)

    return (
        <div
            key={keyDetermined}
            data-attr={`player-list-item-${recordIndex}`}
            className={clsx(
                'PlayerList__item',
                classNameDetermined,
                statusDetermined && `PlayerList__item--status-${statusDetermined}`,
                currentDetermined && `PlayerList__item--current`
            )}
            style={style}
            onClick={() => {
                record.playerPosition && onClick(record)
            }}
            data-tooltip="recording-player-list"
        >
            <div className="h-full rounded flex flex-row items-center justify-between bg-light border border-border px-2">
                <div className="flex flex-row grow gap-1 items-center">
                    {!!expandable && rowExpandable >= 0 ? (
                        <LemonButton
                            noPadding
                            icon={isRowExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                            size="small"
                            active={isRowExpanded}
                            status="stealth"
                            onClick={() => {
                                setIsRowExpanded(!isRowExpanded)
                                if (isRowExpanded) {
                                    expandable?.onRowCollapse?.(record)
                                } else {
                                    expandable?.onRowExpand?.(record)
                                }
                            }}
                            title={isRowExpanded ? 'Show less' : 'Show more'}
                        />
                    ) : (
                        <LemonButton size="small" />
                    )}
                    <div>
                        <IconWindow value="1" className="text-muted" />
                    </div>
                    {contentDetermined}
                </div>
                <div className="flex flex-row gap-3 items-center">
                    {sideContentDetermined}
                    <div className="text-xs">{record.colonTimestamp}</div>
                    <LemonButtonWithPopup
                        data-attr="player-list-item-menu"
                        id="player-list-item-menu"
                        icon={<IconEllipsis />}
                        size="small"
                        status="muted"
                        popup={{
                            placement: 'bottom-end',
                            overlay: (
                                <>
                                    <LemonButton fullWidth status="stealth">
                                        Hello
                                    </LemonButton>
                                </>
                            ),
                        }}
                    />
                </div>
            </div>
        </div>
    )
}

// Without `memo` all rows get rendered when anything in the parent component changes.
export const PlayerListRow = React.memo(PlayerListRowRaw) as typeof PlayerListRowRaw
