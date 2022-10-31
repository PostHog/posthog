import React, { CSSProperties, ReactElement, useMemo } from 'react'
import { RowStatus } from 'scenes/session-recordings/player/list/listLogic'
import clsx from 'clsx'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconEllipsis, IconUnfoldLess, IconUnfoldMore } from 'lib/components/icons'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { boxToSections } from 'lib/components/LemonSelect'
import { LemonDivider } from 'lib/components/LemonDivider'
import { PlayerListExpandableConfig } from 'scenes/session-recordings/player/list/PlayerList'
import { LemonSelectOption } from '@posthog/lemon-ui'

export interface ListRowOption<T>
    extends Pick<LemonSelectOption<T>, 'value' | 'label' | 'tooltip' | 'disabled' | 'data-attr'> {
    onClick?: (record: T) => void
}

export interface ListRowSection<T> {
    options: ListRowOption<T>[]
}

export type ListRowOptions<T> = ListRowSection<T>[] | ListRowOption<T>[]

export interface PlayerListRowProps<T extends Record<string, any>> {
    record: T
    recordIndex: number
    expandable: PlayerListExpandableConfig<T> | undefined
    style: CSSProperties | undefined
    keyDetermined: string | null | undefined
    classNameDetermined: string | null | undefined
    statusDetermined: RowStatus | null | undefined
    expandedDetermined: boolean | null | undefined
    /** If row is current, row will be highlighted with border and prominent ribbon */
    currentDetermined: boolean
    contentDetermined: ReactElement | null | undefined
    sideContentDetermined: ReactElement | null | undefined
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
    const isExpanded = expandable && expandedDetermined

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
                        'cursor-pointer shrink-0 flex gap-3 items-start justify-between p-2',
                        {
                            'text-warning-dark bg-warning-highlight': statusDetermined === RowStatus.Warning,
                            'text-danger-dark bg-danger-highlight': statusDetermined === RowStatus.Error,
                            'text-purple-dark bg-purple-light': statusDetermined === RowStatus.Match,
                            'text-black bg-light': !statusDetermined || statusDetermined === RowStatus.Information,
                        },
                        !isExpanded && 'h-10'
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
                    <div className={clsx('grow h-full', !isExpanded && 'overflow-hidden')}>{contentDetermined}</div>
                    <div className="flex shrink-0 flex-row gap-3 items-center leading-6">
                        {sideContentDetermined}
                        <div className="text-xs leading-6">{record.colonTimestamp}</div>
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
                {isExpanded && (
                    <>
                        <LemonDivider className="my-0" />
                        <div
                            className={clsx(
                                'PlayerList__item__content__expandable',
                                'bg-light overflow-y-scroll w-full h-full'
                            )}
                        >
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
