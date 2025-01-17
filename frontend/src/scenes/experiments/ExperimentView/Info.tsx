import { IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ProgressStatus } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { getExperimentStatus } from '../experimentsLogic'
import { StatusTag } from './components'
import { ExperimentDates } from './ExperimentDates'

export function Info(): JSX.Element {
    const { experiment, featureFlags, metricResults } = useValues(experimentLogic)
    const { updateExperiment, setExperimentStatsVersion, loadMetricResults, loadSecondaryMetricResults } =
        useActions(experimentLogic)

    const { created_by } = experiment

    if (!experiment.feature_flag) {
        return <></>
    }

    const currentStatsVersion = experiment.stats_config?.version || 1

    const lastRefresh = metricResults?.[0]?.last_refresh

    return (
        <div>
            <div className="flex">
                <div className="w-1/2 inline-flex space-x-8">
                    <div className="block" data-attr="experiment-status">
                        <div className="text-xs font-semibold uppercase tracking-wide">Status</div>
                        <StatusTag experiment={experiment} />
                    </div>
                    {experiment.feature_flag && (
                        <div className="block">
                            <div className="text-xs font-semibold uppercase tracking-wide">
                                <span>Feature flag</span>
                            </div>
                            {getExperimentStatus(experiment) === ProgressStatus.Running &&
                                !experiment.feature_flag.active && (
                                    <Tooltip
                                        placement="bottom"
                                        title="Your experiment is running, but the linked flag is disabled. No data is being collected."
                                    >
                                        <IconWarning
                                            style={{ transform: 'translateY(2px)' }}
                                            className="mr-1 text-danger"
                                            fontSize="18px"
                                        />
                                    </Tooltip>
                                )}
                            <CopyToClipboardInline
                                iconStyle={{ color: 'var(--lemon-button-icon-opacity)' }}
                                className="font-normal text-sm"
                                description="feature flag key"
                            >
                                {experiment.feature_flag.key}
                            </CopyToClipboardInline>
                            <Link
                                target="_blank"
                                className="font-semibold"
                                to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                            >
                                <IconOpenInNew fontSize="18" />
                            </Link>
                        </div>
                    )}
                    {featureFlags[FEATURE_FLAGS.EXPERIMENT_STATS_V2] && (
                        <div className="block">
                            <div className="text-xs font-semibold uppercase tracking-wide">
                                <span>Stats Version</span>
                            </div>
                            <div className="flex gap-1">
                                {[1, 2].map((version) => (
                                    <LemonButton
                                        key={version}
                                        size="xsmall"
                                        type="tertiary"
                                        active={currentStatsVersion === version}
                                        onClick={() => {
                                            setExperimentStatsVersion(version)
                                        }}
                                    >
                                        v{version}
                                    </LemonButton>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto inline-flex space-x-8">
                        {lastRefresh && (
                            <div className="block">
                                <div className="text-xs font-semibold uppercase tracking-wide">Last refreshed</div>
                                <div className="inline-flex space-x-2">
                                    <span
                                        className={`${
                                            lastRefresh
                                                ? dayjs().diff(dayjs(lastRefresh), 'hours') > 12
                                                    ? 'text-danger'
                                                    : dayjs().diff(dayjs(lastRefresh), 'hours') > 6
                                                    ? 'text-warning'
                                                    : ''
                                                : ''
                                        }`}
                                    >
                                        {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
                                    </span>
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        onClick={() => {
                                            loadMetricResults(true)
                                            loadSecondaryMetricResults(true)
                                        }}
                                        data-attr="refresh-experiment"
                                        icon={<IconRefresh />}
                                        tooltip="Refresh experiment results"
                                    />
                                </div>
                            </div>
                        )}
                        <ExperimentDates />
                        <div className="block">
                            <div className="text-xs font-semibold uppercase tracking-wide">Created by</div>
                            {created_by && <ProfilePicture user={created_by} size="md" showName />}
                        </div>
                    </div>
                </div>
            </div>
            <div className="block mt-4">
                <div className="text-xs font-semibold uppercase tracking-wide">Description</div>
                <EditableField
                    className="py-2"
                    multiline
                    markdown
                    name="description"
                    value={experiment.description || ''}
                    placeholder="Add your hypothesis for this test (optional)"
                    onSave={(value) => updateExperiment({ description: value })}
                    maxLength={400}
                    data-attr="experiment-description"
                    compactButtons
                />
            </div>
        </div>
    )
}
