import { IconPencil, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'

import { ProgressStatus } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { getExperimentStatus } from '../experimentsLogic'
import { StatusTag } from './components'
import { ExperimentDates } from './ExperimentDates'

export function Info(): JSX.Element {
    const {
        experiment,
        featureFlags,
        metricResults,
        metricResultsLoading,
        secondaryMetricResultsLoading,
        isDescriptionModalOpen,
    } = useValues(experimentLogic)
    const {
        updateExperiment,
        setExperimentStatsVersion,
        refreshExperimentResults,
        openDescriptionModal,
        closeDescriptionModal,
    } = useActions(experimentLogic)

    const [tempDescription, setTempDescription] = useState(experiment.description || '')

    useEffect(() => {
        setTempDescription(experiment.description || '')
    }, [experiment.description])

    const { created_by } = experiment

    if (!experiment.feature_flag) {
        return <></>
    }

    const currentStatsVersion = experiment.stats_config?.version || 1

    const lastRefresh = metricResults?.[0]?.last_refresh

    return (
        <div>
            <div className="flex flex-wrap justify-between gap-4">
                <div className="inline-flex space-x-8">
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
                    <div className="block">
                        <div className="text-xs font-semibold uppercase tracking-wide">
                            <span>Stats Engine</span>
                        </div>
                        <div className="flex gap-1">Bayesian</div>
                    </div>
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

                <div className="flex flex-col">
                    <div className="inline-flex space-x-8">
                        {experiment.start_date && (
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
                                        {metricResultsLoading || secondaryMetricResultsLoading
                                            ? 'Loading…'
                                            : lastRefresh
                                            ? dayjs(lastRefresh).fromNow()
                                            : 'a while ago'}
                                    </span>
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        onClick={() => {
                                            refreshExperimentResults(true)
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
                <div className="flex items-center gap-2">
                    <div className="text-xs font-semibold uppercase tracking-wide">Hypothesis</div>
                    <LemonButton type="secondary" size="xsmall" icon={<IconPencil />} onClick={openDescriptionModal} />
                </div>
                {experiment.description ? (
                    <p className="py-2 m-0">{experiment.description}</p>
                ) : (
                    <p className="py-2 m-0 text-muted">Add your hypothesis for this test</p>
                )}

                <LemonModal
                    isOpen={isDescriptionModalOpen}
                    onClose={closeDescriptionModal}
                    title="Edit hypothesis"
                    footer={
                        <div className="flex items-center gap-2 justify-end">
                            <LemonButton type="secondary" onClick={closeDescriptionModal}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    updateExperiment({ description: tempDescription })
                                    closeDescriptionModal()
                                }}
                            >
                                Save
                            </LemonButton>
                        </div>
                    }
                >
                    <LemonTextArea
                        className="w-full"
                        value={tempDescription}
                        onChange={(value) => setTempDescription(value)}
                        placeholder="Add your hypothesis for this test (optional)"
                        minRows={6}
                        maxLength={400}
                    />
                </LemonModal>
            </div>
        </div>
    )
}
