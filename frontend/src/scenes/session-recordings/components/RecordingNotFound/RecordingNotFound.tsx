import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { SessionRecordingRetentionPeriod } from '~/types'

import { RecordingNotFoundLogicProps, recordingNotFoundLogic } from './recordingNotFoundLogic'

export function RecordingNotFound({ sessionRecordingId }: RecordingNotFoundLogicProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.REPLAY_SHOW_NEW_404] === 'show') {
        return <RecordingNotFoundV2 sessionRecordingId={sessionRecordingId} />
    }

    return (
        <NotFound
            object="Recording"
            caption={
                <>
                    The requested recording could not be found. It may still be processing, may have been deleted due to
                    age, or recording may not be enabled. Please check your{' '}
                    <Link to={urls.settings('project-replay')}>project settings</Link>
                    to ensure that recording is turned on and enabled for the relevant domain. You can also refer to the{' '}
                    <Link to="https://posthog.com/docs/session-replay/troubleshooting#recording-not-found">
                        troubleshooting guide
                    </Link>{' '}
                    for more information.
                    {currentTeam?.session_recording_opt_in ? (
                        <LemonBanner type="info" className="mt-4 max-w-xl mx-auto">
                            <div className="flex justify-between items-center">
                                <p>Session replay is enabled for this project</p>
                                <LemonButton
                                    data-attr="recording-404-edit-settings"
                                    type="secondary"
                                    size="small"
                                    to={urls.settings('project-replay')}
                                >
                                    Edit settings
                                </LemonButton>
                            </div>
                        </LemonBanner>
                    ) : (
                        <LemonBanner type="warning" className="mt-4 max-w-xl mx-auto">
                            <div className="flex justify-between items-center">
                                <p>Session replay is disabled for this project</p>
                                <LemonButton
                                    data-attr="recording-404-edit-settings"
                                    type="secondary"
                                    size="small"
                                    to={urls.settings('project-replay')}
                                >
                                    Edit settings
                                </LemonButton>
                            </div>
                        </LemonBanner>
                    )}
                </>
            }
        />
    )
}

function MinimumDurationCard(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <LemonCard className="mt-3 max-w-xl mx-auto">
            <div className="flex items-center gap-3">
                <LemonTag type="warning">Minimum duration</LemonTag>
                <div className="grow">
                    <p className="mb-1">
                        We don't have a recording for this session because it was shorter than your minimum duration
                        setting.
                    </p>
                    {currentTeam?.session_recording_minimum_duration_milliseconds ? (
                        <p className="text-muted text-sm mb-0">
                            Current minimum: {(currentTeam.session_recording_minimum_duration_milliseconds ?? 0) / 1000}
                            s
                        </p>
                    ) : null}
                </div>
            </div>
            <LemonDivider className="my-3" />
            <LemonBanner
                type="info"
                className="mt-1"
                action={{
                    to: urls.settings('project-replay'),
                    children: 'Edit settings',
                    size: 'small',
                    type: 'secondary',
                    'data-attr': 'recording-404-edit-settings',
                }}
            >
                To avoid this in the future, set the minimum duration lower.
            </LemonBanner>
        </LemonCard>
    )
}

function SamplingRateCard(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <LemonCard className="mt-3 max-w-xl mx-auto">
            <div className="flex items-center gap-3">
                <LemonTag type="warning">Sampling rate</LemonTag>
                <div className="grow">
                    <p className="mb-1">
                        We don't have a recording for this session because your sampling rate excluded it.
                    </p>
                    {currentTeam?.session_recording_sample_rate ? (
                        <p className="text-muted text-sm mb-0">
                            Current sampling:{' '}
                            {(() => {
                                const sr = currentTeam.session_recording_sample_rate
                                const pct = sr != null ? parseFloat(String(sr)) * 100 : NaN
                                return Number.isFinite(pct) ? `${Math.round(pct)}%` : sr
                            })()}
                        </p>
                    ) : null}
                </div>
            </div>
            <LemonDivider className="my-3" />
            <LemonBanner
                type="info"
                className="mt-1"
                action={{
                    to: urls.settings('project-replay'),
                    children: 'Edit settings',
                    size: 'small',
                    type: 'secondary',
                    'data-attr': 'recording-404-edit-settings',
                }}
            >
                To avoid this in the future, set the sampling rate higher.
            </LemonBanner>
        </LemonCard>
    )
}

function ExpiredCard(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <LemonCard className="mt-3 max-w-xl mx-auto">
            <div className="flex items-center gap-3">
                <LemonTag type="warning">Retention</LemonTag>
                <div className="grow">
                    <p className="mb-1">We don't have a recording for this session because it has expired.</p>
                    {(() => {
                        const retention = (currentTeam?.session_recording_retention_period ??
                            '30d') as SessionRecordingRetentionPeriod
                        const label = (
                            {
                                '30d': '30 days',
                                '90d': '90 days',
                                '1y': '1 year',
                                '5y': '5 years',
                                legacy: '30 days',
                            } as Record<SessionRecordingRetentionPeriod, string>
                        )[retention]
                        return <p className="text-muted text-sm mb-0">Current retention: {label}</p>
                    })()}
                </div>
            </div>
            <LemonDivider className="my-3" />
            <LemonBanner
                type="info"
                className="mt-1"
                action={{
                    to: urls.settings('project-replay'),
                    children: 'Edit settings',
                    size: 'small',
                    type: 'secondary',
                    'data-attr': 'recording-404-edit-settings',
                }}
            >
                To avoid this in the future, set a higher retention period.
            </LemonBanner>
        </LemonCard>
    )
}

function TriggersCard(): JSX.Element {
    return (
        <LemonCard className="mt-3 max-w-xl mx-auto">
            <div className="flex items-center gap-3">
                <LemonTag type="warning">Recording triggers</LemonTag>
                <div className="grow">
                    <p className="mb-1">
                        We don't have a recording for this session because it didn't match your recording triggers.
                    </p>
                </div>
            </div>
            <LemonDivider className="my-3" />
            <LemonBanner
                type="info"
                className="mt-1"
                action={{
                    to: urls.settings('project-replay'),
                    children: 'Edit settings',
                    size: 'small',
                    type: 'secondary',
                    'data-attr': 'recording-404-edit-settings',
                }}
            >
                To avoid this in the future, change your recording triggers.
            </LemonBanner>
        </LemonCard>
    )
}

function ReplayDisabledCard(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <LemonCard className="mt-3 max-w-xl mx-auto">
            <div className="flex items-center gap-3">
                <LemonTag type="warning">Session replay</LemonTag>
                <div className="grow">
                    <p className="mb-1">
                        We don't have a recording for this session because session replay is turned off.
                    </p>
                    {typeof currentTeam?.session_recording_opt_in === 'boolean' ? (
                        <p className="text-muted text-sm mb-0">
                            Current status: {currentTeam.session_recording_opt_in ? 'On' : 'Off'}
                        </p>
                    ) : null}
                </div>
            </div>
            <LemonDivider className="my-3" />
            <LemonBanner
                type="info"
                className="mt-1"
                action={{
                    to: urls.settings('project-replay'),
                    children: 'Edit settings',
                    size: 'small',
                    type: 'secondary',
                    'data-attr': 'recording-404-edit-settings',
                }}
            >
                To avoid this in the future, turn on session recordings.
            </LemonBanner>
        </LemonCard>
    )
}

function GeneralInfoCard(): JSX.Element {
    return (
        <LemonCard className="mt-3 max-w-xl mx-auto">
            <div className="flex items-center gap-3">
                <LemonTag type="warning">Session recording</LemonTag>
                <div className="grow">
                    <p className="mb-1">We don't have a recording for this session.</p>
                </div>
            </div>
            <LemonDivider className="my-3" />
            <LemonBanner
                type="info"
                className="mt-1"
                action={{
                    to: urls.settings('project-replay'),
                    children: 'Edit settings',
                    size: 'small',
                    type: 'secondary',
                    'data-attr': 'recording-404-edit-settings',
                }}
            >
                To avoid this in the future, check your recording settings.
            </LemonBanner>
        </LemonCard>
    )
}

function SessionMissingCard(): JSX.Element {
    return (
        <LemonCard className="mt-3 max-w-xl mx-auto">
            <div className="flex items-center gap-3">
                <LemonTag type="warning">Session</LemonTag>
                <div className="grow">
                    <p className="mb-0">
                        We don't have a recording for this session because the session does not exist.
                    </p>
                </div>
            </div>
        </LemonCard>
    )
}

function DomainNotAllowedCard(): JSX.Element {
    return (
        <LemonCard className="mt-3 max-w-xl mx-auto">
            <div className="flex items-center gap-3">
                <LemonTag type="warning">Domain not allowed</LemonTag>
                <div className="grow">
                    <p className="mb-1">
                        We don't have a recording for this session because the page's domain isn't allowed in your
                        recording settings.
                    </p>
                </div>
            </div>
            <LemonDivider className="my-3" />
            <LemonBanner
                type="info"
                className="mt-1"
                action={{
                    to: urls.settings('project-replay'),
                    children: 'Edit settings',
                    size: 'small',
                    type: 'secondary',
                    'data-attr': 'recording-404-edit-settings',
                }}
            >
                To avoid this in the future, add the domain to your allowed list.
            </LemonBanner>
        </LemonCard>
    )
}

function UrlBlocklistedCard(): JSX.Element {
    return (
        <LemonCard className="mt-3 max-w-xl mx-auto">
            <div className="flex items-center gap-3">
                <LemonTag type="warning">URL blocklisted</LemonTag>
                <div className="grow">
                    <p className="mb-1">
                        We don't have a recording for this session because this URL is blocklisted in your recording
                        settings.
                    </p>
                </div>
            </div>
            <LemonDivider className="my-3" />
            <LemonBanner
                type="info"
                className="mt-1"
                action={{
                    to: urls.settings('project-replay'),
                    children: 'Edit settings',
                    size: 'small',
                    type: 'secondary',
                    'data-attr': 'recording-404-edit-settings',
                }}
            >
                To avoid this in the future, remove or adjust the URL blocklist pattern.
            </LemonBanner>
        </LemonCard>
    )
}

export function RecordingNotFoundV2({ sessionRecordingId }: RecordingNotFoundLogicProps): JSX.Element {
    const logic = recordingNotFoundLogic({ sessionRecordingId: sessionRecordingId })
    const { isLoading, missingReason } = useValues(logic)

    if (isLoading) {
        return <LemonSkeleton />
    }

    var caption = <GeneralInfoCard />
    switch (missingReason) {
        case 'session_missing':
            caption = <SessionMissingCard />
            break
        case 'retention_expired':
            caption = <ExpiredCard />
            break
        case 'replay_disabled':
            caption = <ReplayDisabledCard />
            break
        case 'domain_not_allowed':
            caption = <DomainNotAllowedCard />
            break
        case 'url_blocklisted':
            caption = <UrlBlocklistedCard />
            break
        case 'below_min_duration':
            caption = <MinimumDurationCard />
            break
        case 'sampled_out':
            caption = <SamplingRateCard />
            break
        case 'triggers_not_matched':
            caption = <TriggersCard />
            break
        case 'unknown':
            caption = <GeneralInfoCard />
            break
    }

    return <NotFound object="Recording" hideLostInSpace={true} caption={caption} />
}
