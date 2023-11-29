import './PlayerMeta.scss'

import { Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { percentage } from 'lib/utils'
import { DraggableToNotebook } from 'scenes/notebooks/AddToNotebook/DraggableToNotebook'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { playerMetaLogic } from 'scenes/session-recordings/player/playerMetaLogic'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { Logo } from '~/toolbar/assets/Logo'

import { PlayerMetaLinks } from './PlayerMetaLinks'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerMode } from './sessionRecordingPlayerLogic'

function SessionPropertyMeta(props: {
    fullScreen: boolean
    iconProperties: Record<string, any>
    predicate: (x: string) => boolean
}): JSX.Element {
    return (
        <div className="flex flex-row flex-nowrap shrink-0 gap-2 text-muted-alt">
            <span className="flex items-center gap-1 whitespace-nowrap">
                <PropertyIcon
                    noTooltip={!props.fullScreen}
                    property="$browser"
                    value={props.iconProperties['$browser']}
                />
                {!props.fullScreen ? props.iconProperties['$browser'] : null}
            </span>
            <span className="flex items-center gap-1 whitespace-nowrap">
                <PropertyIcon
                    noTooltip={!props.fullScreen}
                    property="$device_type"
                    value={props.iconProperties['$device_type'] || props.iconProperties['$initial_device_type']}
                />
                {!props.fullScreen
                    ? props.iconProperties['$device_type'] || props.iconProperties['$initial_device_type']
                    : null}
            </span>
            <span className="flex items-center gap-1 whitespace-nowrap">
                <PropertyIcon noTooltip={!props.fullScreen} property="$os" value={props.iconProperties['$os']} />
                {!props.fullScreen ? props.iconProperties['$os'] : null}
            </span>
            {props.iconProperties['$geoip_country_code'] && (
                <span className="flex items-center gap-1 whitespace-nowrap">
                    <PropertyIcon
                        noTooltip={!props.fullScreen}
                        property="$geoip_country_code"
                        value={props.iconProperties['$geoip_country_code']}
                    />
                    {
                        props.fullScreen &&
                            [
                                props.iconProperties['$geoip_city_name'],
                                props.iconProperties['$geoip_subdivision_1_code'],
                            ]
                                .filter(props.predicate)
                                .join(', ') /* [city, state] */
                    }
                </span>
            )}
        </div>
    )
}

export function PlayerMeta(): JSX.Element {
    const { sessionRecordingId, logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)

    const {
        sessionPerson,
        resolution,
        lastPageviewEvent,
        lastUrl,
        scale,
        currentWindowIndex,
        startTime,
        sessionPlayerMetaDataLoading,
        sessionProperties,
    } = useValues(playerMetaLogic(logicProps))

    const { ref, size } = useResizeBreakpoints({
        0: 'compact',
        550: 'normal',
    })

    const isSmallPlayer = size === 'compact'

    const mode = logicProps.mode ?? SessionRecordingPlayerMode.Standard
    const whitelabel = getCurrentExporterData()?.whitelabel ?? false

    const resolutionView = sessionPlayerMetaDataLoading ? (
        <LemonSkeleton className="w-1/3 h-4" />
    ) : resolution ? (
        <Tooltip
            placement="bottom"
            title={
                <>
                    The resolution of the page as it was captured was{' '}
                    <b>
                        {resolution.width} x {resolution.height}
                    </b>
                    <br />
                    You are viewing the replay at <b>{percentage(scale, 1, true)}</b> of the original size
                </>
            }
        >
            <span className="text-muted-alt text-xs">
                {resolution && (
                    <>
                        {resolution.width} x {resolution.height} {!isSmallPlayer && `(${percentage(scale, 1, true)})`}
                    </>
                )}
            </span>
        </Tooltip>
    ) : null

    if (mode === SessionRecordingPlayerMode.Sharing) {
        if (whitelabel) {
            return <></>
        }
        return (
            <div className="PlayerMeta">
                <div className="flex justify-between items-center m-2">
                    {!whitelabel ? (
                        <Tooltip title="Powered by PostHog" placement="right">
                            <Link to={'https://posthog.com'} className="flex items-center" target="blank">
                                <Logo />
                            </Link>
                        </Tooltip>
                    ) : null}
                    {resolutionView}
                </div>
            </div>
        )
    }

    return (
        <DraggableToNotebook href={urls.replaySingle(logicProps.sessionRecordingId)} onlyWithModifierKey>
            <div
                ref={ref}
                className={clsx('PlayerMeta', {
                    'PlayerMeta--fullscreen': isFullScreen,
                })}
            >
                <div
                    className={clsx(
                        'PlayerMeta__top flex items-center gap-2 shrink-0 p-2',
                        isFullScreen ? ' text-xs' : 'border-b'
                    )}
                >
                    <div className="ph-no-capture">
                        {!sessionPerson ? (
                            <LemonSkeleton.Circle className="w-8 h-8" />
                        ) : (
                            <ProfilePicture name={asDisplay(sessionPerson)} />
                        )}
                    </div>
                    <div className="overflow-hidden ph-no-capture flex-1">
                        <div>
                            {!sessionPerson || !startTime ? (
                                <LemonSkeleton className="w-1/3 h-4 my-1" />
                            ) : (
                                <div className="flex gap-1">
                                    <span className="font-bold whitespace-nowrap truncate">
                                        <PersonDisplay person={sessionPerson} withIcon={false} noEllipsis={true} />
                                    </span>
                                    {'·'}
                                    <TZLabel
                                        time={dayjs(startTime)}
                                        formatDate="MMMM DD, YYYY"
                                        formatTime="h:mm A"
                                        showPopover={false}
                                    />
                                </div>
                            )}
                        </div>
                        <div className="text-muted">
                            {sessionPlayerMetaDataLoading ? (
                                <LemonSkeleton className="w-1/4 h-4 my-1" />
                            ) : sessionProperties ? (
                                <SessionPropertyMeta
                                    fullScreen={isFullScreen}
                                    iconProperties={sessionProperties}
                                    predicate={(x) => !!x}
                                />
                            ) : null}
                        </div>
                    </div>

                    {sessionRecordingId && <PlayerMetaLinks />}
                </div>
                <div
                    className={clsx('flex items-center justify-between gap-2 whitespace-nowrap overflow-hidden', {
                        'p-2 h-10': !isFullScreen,
                        'p-1 px-3 text-xs h-12': isFullScreen,
                    })}
                >
                    {sessionPlayerMetaDataLoading ? (
                        <LemonSkeleton className="w-1/3 h-4 my-1" />
                    ) : (
                        <>
                            <Tooltip
                                title={
                                    <>
                                        Window {currentWindowIndex + 1}.
                                        <br />
                                        Each recording window translates to a distinct browser tab or window.
                                    </>
                                }
                            >
                                <IconWindow value={currentWindowIndex + 1} className="text-muted-alt" />
                            </Tooltip>

                            {lastUrl && (
                                <span className="flex items-center gap-2 truncate">
                                    <span>·</span>
                                    <span className="flex items-center gap-1 truncate">
                                        <Tooltip title="Click to open url">
                                            <Link to={lastUrl} target="_blank" className="truncate">
                                                {lastUrl}
                                            </Link>
                                        </Tooltip>
                                        <span className="flex items-center">
                                            <CopyToClipboardInline
                                                description="current url"
                                                explicitValue={lastUrl}
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
                    {resolutionView}
                </div>
            </div>
        </DraggableToNotebook>
    )
}
