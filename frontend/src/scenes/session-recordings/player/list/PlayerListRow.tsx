import React, { CSSProperties, ReactNode, useMemo } from 'react'
import { ExpandableConfig } from 'lib/components/LemonTable'
import { RowStatus } from 'scenes/session-recordings/player/list/listLogic'
import clsx from 'clsx'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconEllipsis, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { boxToSections } from 'lib/components/LemonSelect'
import { LemonDivider } from 'lib/components/LemonDivider'

export interface ListRowOption<T> {
    label: string | JSX.Element
    disabled?: boolean
    tooltip?: string
    'data-attr'?: string
    onClick?: (record: T) => void
}

export interface ListRowSection<T> {
    options: ListRowOption<T>[]
}

export type ListRowOptions<T> = ListRowSection<T>[] | ListRowOption<T>[]

export interface PlayerListRowProps<T extends Record<string, any>> {
    record: T
    recordIndex: number
    expandable: ExpandableConfig<T> | undefined
    style: CSSProperties | undefined
    keyDetermined: string | null | undefined
    classNameDetermined: string | null | undefined
    statusDetermined: RowStatus | null | undefined
    expandedDetermined: boolean | null | undefined
    /** If row is current, row will be highlighted with border and prominent ribbon */
    currentDetermined: boolean
    contentDetermined: ReactNode
    sideContentDetermined: ReactNode
    onClick: (record: T) => void
    optionsDetermined: ListRowOptions<T>
    /** Used to pause any interactions while player list is still loading **/
    loading?: boolean
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
    expandedDetermined,
    sideContentDetermined,
    optionsDetermined,
    onClick,
    loading,
}: PlayerListRowProps<T>): JSX.Element {
    const [sections, allOptions] = useMemo(() => boxToSections(optionsDetermined), [optionsDetermined])

    return (
        <div
            key={keyDetermined}
            data-attr={`player-list-item-${recordIndex}`}
            className={clsx('PlayerList__item', 'flex flex-col justify-start', classNameDetermined)}
            style={style}
            onClick={() => {
                record.playerPosition && onClick(record)
            }}
            data-tooltip="recording-player-list"
        >
            <div
                className={clsx(
                    'PlayerList__item__content',
                    'flex flex-col h-full rounded border overflow-hidden',
                    currentDetermined ? 'PlayerList__item__content--current border-primary' : 'border-border'
                )}
            >
                <div
                    className={clsx(
                        'PlayerList__item__content__header',
                        'cursor-pointer h-10 shrink-0 flex flex-row gap-3 items-center justify-between px-2 bg-light',
                        {
                            'text-warning-dark bg-warning-highlight': statusDetermined === RowStatus.Warning,
                            'text-danger-dark bg-danger-highlight': statusDetermined === RowStatus.Error,
                            'text-indigo bg-purple-light': statusDetermined === RowStatus.Match,
                        }
                    )}
                >
                    <div className="flex flex-row items-center">
                        {!!expandable ? (
                            <LemonButton
                                noPadding
                                disabled={!!loading}
                                className="shrink-0 mr-1"
                                icon={expandedDetermined ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                size="small"
                                active={!!expandedDetermined}
                                status="stealth"
                                onClick={(event) => {
                                    event.stopPropagation()
                                    if (expandedDetermined) {
                                        expandable?.onRowCollapse?.(record, recordIndex)
                                    } else {
                                        expandable?.onRowExpand?.(record, recordIndex)
                                    }
                                }}
                                title={expandedDetermined ? 'Show less' : 'Show more'}
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
                        {allOptions.length > 0 && (
                            <LemonButtonWithPopup
                                data-attr="player-list-item-menu"
                                id="player-list-item-menu"
                                icon={<IconEllipsis />}
                                size="small"
                                status="muted"
                                onClick={(event) => {
                                    event.stopPropagation()
                                }}
                                popup={{
                                    placement: 'bottom-end',
                                    overlay: sections.map((section, i) => (
                                        <React.Fragment key={i}>
                                            {section.options.map((option: ListRowOption<T>, index) => (
                                                <LemonButton
                                                    key={index}
                                                    tooltip={option.tooltip}
                                                    onClick={(event) => {
                                                        event.stopPropagation()
                                                        option?.onClick?.(record)
                                                    }}
                                                    status="stealth"
                                                    disabled={option.disabled}
                                                    fullWidth
                                                    data-attr={option['data-attr']}
                                                >
                                                    {option.label}
                                                </LemonButton>
                                            ))}
                                            {i < sections.length - 1 ? <LemonDivider /> : null}
                                        </React.Fragment>
                                    )),
                                }}
                            />
                        )}
                    </div>
                </div>
                {expandable && expandedDetermined && (
                    <>
                        <LemonDivider className="my-0" />
                        <div className={clsx('PlayerList__item__content__expandable', 'overflow-y-scroll px-6')}>
                            {expandable.expandedRowRender(record, recordIndex)}
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

// Without `memo` all rows get rendered when anything in the parent component changes.
export const PlayerListRow = React.memo(PlayerListRowRaw) as typeof PlayerListRowRaw
