import './PlayerMeta.scss'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { useActions, useValues } from 'kea'
import { asDisplay, PersonHeader } from 'scenes/persons/PersonHeader'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { percentage } from 'lib/utils'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import clsx from 'clsx'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { playerSettingsLogic } from './playerSettingsLogic'
import { IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { CSSTransition } from 'react-transition-group'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { SessionRecordingPlayerLogicProps } from './sessionRecordingPlayerLogic'
import { PlayerMetaLinks } from './PlayerMetaLinks'

export function PlayerMeta(props: SessionRecordingPlayerLogicProps): JSX.Element {
    const {
        sessionPerson,
        resolution,
        lastPageviewEvent,
        scale,
        currentWindowIndex,
        recordingStartTime,
        sessionPlayerMetaDataLoading,
        windowIds,
    } = useValues(playerMetaLogic(props))

    const { isFullScreen, isMetadataExpanded } = useValues(playerSettingsLogic)
    const { setIsMetadataExpanded } = useActions(playerSettingsLogic)

    const iconProperties = lastPageviewEvent?.properties || sessionPerson?.properties

    const { ref, size } = useResizeBreakpoints({
        0: 'compact',
        550: 'normal',
    })

    const isSmallPlayer = size === 'compact'

    return (
        <div
            ref={ref}
            className={clsx('PlayerMeta', {
                'PlayerMeta--fullscreen': isFullScreen,
            })}
        >
            {isFullScreen && (
                <div className="PlayerMeta__escape">
                    <div className="bg-muted-dark text-white px-2 py-1 rounded shadow my-1 mx-auto">
                        Press <kbd className="font-bold">Esc</kbd> to exit full screen
                    </div>
                </div>
            )}

            <div
                className={clsx('PlayerMeta__top flex items-center gap-2 shrink-0', {
                    'p-3 border-b': !isFullScreen,
                    'px-3 p-1 text-xs': isFullScreen,
                })}
            >
                <div className="mr-2 ph-no-capture">
                    {!sessionPerson ? (
                        <LemonSkeleton.Circle className="w-12 h-12" />
                    ) : (
                        <ProfilePicture name={asDisplay(sessionPerson)} size={!isFullScreen ? 'xxl' : 'md'} />
                    )}
                </div>
                <div className="overflow-hidden ph-no-capture flex-1">
                    <div className="font-bold">
                        {!sessionPerson || !recordingStartTime ? (
                            <LemonSkeleton className="w-1/3 my-1" />
                        ) : (
                            <div className="flex gap-1">
                                <PersonHeader person={sessionPerson} withIcon={false} noEllipsis={true} />
                                {'·'}
                                <TZLabel
                                    time={dayjs(recordingStartTime)}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="h:mm A"
                                    showPopover={false}
                                />
                            </div>
                        )}
                    </div>
                    <div className="text-muted">
                        {sessionPlayerMetaDataLoading ? (
                            <LemonSkeleton className="w-1/4 my-1" />
                        ) : iconProperties ? (
                            <div className="flex flex-row flex-nowrap shrink-0 gap-2 text-muted-alt">
                                <span className="flex items-center gap-1 whitespace-nowrap">
                                    <PropertyIcon
                                        noTooltip={!isFullScreen}
                                        property="$browser"
                                        value={iconProperties['$browser']}
                                    />
                                    {!isFullScreen ? iconProperties['$browser'] : null}
                                </span>
                                <span className="flex items-center gap-1 whitespace-nowrap">
                                    <PropertyIcon
                                        noTooltip={!isFullScreen}
                                        property="$device_type"
                                        value={iconProperties['$device_type'] || iconProperties['$initial_device_type']}
                                    />
                                    {!isFullScreen
                                        ? iconProperties['$device_type'] || iconProperties['$initial_device_type']
                                        : null}
                                </span>
                                <span className="flex items-center gap-1 whitespace-nowrap">
                                    <PropertyIcon
                                        noTooltip={!isFullScreen}
                                        property="$os"
                                        value={iconProperties['$os']}
                                    />
                                    {!isFullScreen ? iconProperties['$os'] : null}
                                </span>
                                {iconProperties['$geoip_country_code'] && (
                                    <span className="flex items-center gap-1 whitespace-nowrap">
                                        <PropertyIcon
                                            noTooltip={!isFullScreen}
                                            property="$geoip_country_code"
                                            value={iconProperties['$geoip_country_code']}
                                        />
                                        {!isFullScreen &&
                                            `${iconProperties['$geoip_city_name'] || ''}${
                                                iconProperties['$geoip_subdivision_1_code'] &&
                                                iconProperties['$geoip_city_name']
                                                    ? ', '
                                                    : ''
                                            }${iconProperties['$geoip_subdivision_1_code'] || ''}`}
                                    </span>
                                )}
                            </div>
                        ) : null}
                    </div>
                </div>

                <LemonButton
                    className={clsx('PlayerMeta__expander', isFullScreen ? 'rotate-90' : '')}
                    status="stealth"
                    active={isMetadataExpanded}
                    onClick={() => setIsMetadataExpanded(!isMetadataExpanded)}
                    icon={isMetadataExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                    tooltip={isMetadataExpanded ? 'Hide person properties' : 'Show person properties'}
                    tooltipPlacement={isFullScreen ? 'bottom' : 'left'}
                />

                {props.sessionRecordingId ? <PlayerMetaLinks {...props} /> : null}
            </div>
            {sessionPerson && (
                <CSSTransition
                    in={isMetadataExpanded}
                    timeout={200}
                    classNames="PlayerMetaPersonProperties-"
                    mountOnEnter
                    unmountOnExit
                >
                    <div className="PlayerMetaPersonProperties">
                        {Object.keys(sessionPerson.properties).length ? (
                            <PropertiesTable properties={sessionPerson.properties} />
                        ) : (
                            <p className="text-center m-4">There are no properties.</p>
                        )}
                    </div>
                </CSSTransition>
            )}
            <div
                className={clsx(
                    'PlayerMeta__bottom flex items-center justify-between gap-2 whitespace-nowrap overflow-hidden',
                    {
                        'p-3': !isFullScreen,
                        'p-1 px-3 text-xs h-12': isFullScreen,
                    }
                )}
            >
                {sessionPlayerMetaDataLoading || currentWindowIndex === -1 ? (
                    <LemonSkeleton className="w-1/3 my-1" />
                ) : (
                    <>
                        <IconWindow value={currentWindowIndex + 1} className="text-muted-alt" />
                        {windowIds.length > 1 && !isSmallPlayer ? (
                            <div className="text-muted-alt">Window {currentWindowIndex + 1}</div>
                        ) : null}

                        {lastPageviewEvent?.properties?.['$current_url'] && (
                            <span className="flex items-center gap-2 truncate">
                                <span>·</span>
                                <span className="flex items-center gap-1 truncate">
                                    <Tooltip title="Click to open url">
                                        <Link
                                            to={lastPageviewEvent?.properties['$current_url']}
                                            target="_blank"
                                            className="truncate"
                                        >
                                            {lastPageviewEvent?.properties['$current_url']}
                                        </Link>
                                    </Tooltip>
                                    <span className="flex items-center">
                                        <CopyToClipboardInline
                                            description="current url"
                                            explicitValue={lastPageviewEvent?.properties['$current_url']}
                                            iconStyle={{ color: 'var(--muted-alt)' }}
                                        />
                                    </span>
                                </span>
                            </span>
                        )}
                        {lastPageviewEvent?.properties?.['$screen_name'] && (
                            <span className="flex items-center gap-2 truncate">
                                <span>·</span>
                                <span className="flex items-center gap-1 truncate">
                                    {lastPageviewEvent?.properties['$screen_name']}
                                </span>
                            </span>
                        )}
                    </>
                )}
                <div className={clsx('flex-1', isSmallPlayer ? 'min-w-4' : 'min-w-20')} />
                {sessionPlayerMetaDataLoading ? (
                    <LemonSkeleton className="w-1/3" />
                ) : (
                    <span className="text-muted-alt">
                        {resolution && (
                            <>
                                Resolution: {resolution.width} x {resolution.height}{' '}
                                {!isSmallPlayer && `(${percentage(scale, 1, true)})`}
                            </>
                        )}
                    </span>
                )}
            </div>
        </div>
    )
}
