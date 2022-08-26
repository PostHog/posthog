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
            className={clsx('PlayerList__item', classNameDetermined)}
            style={style}
            onClick={() => {
                record.playerPosition && onClick(record)
            }}
            data-tooltip="recording-player-list"
        >
            <div
                className={clsx(
                    'PlayerList__item__content',
                    'cursor-pointer h-full rounded flex flex-row gap-3 items-center justify-between border px-2',
                    {
                        'bg-light': statusDetermined === RowStatus.Information,
                        'text-warning-dark bg-warning-highlight': statusDetermined === RowStatus.Warning,
                        'text-danger-dark bg-danger-highlight': statusDetermined === RowStatus.Error,
                        'text-indigo bg-purple-light': statusDetermined === RowStatus.Match,
                    },
                    currentDetermined ? 'PlayerList__item__content--current border-primary' : 'border-border'
                )}
            >
                <div className="flex flex-row items-center">
                    {!!expandable && rowExpandable >= 0 ? (
                        <LemonButton
                            noPadding
                            className="shrink-0"
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
                        <IconWindow value="1" className="text-muted shrink-0" />
                    </div>
                </div>
                <div className="grow overflow-hidden">{contentDetermined}</div>
                <div className="flex shrink-0 flex-row gap-3 items-center text-muted">
                    {sideContentDetermined}
                    <div style={{ fontSize: 11 }}>{record.colonTimestamp}</div>
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
