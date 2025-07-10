import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconGear, IconPencil, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal, Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ExperimentStatsMethod, ProgressStatus } from '~/types'

import { CONCLUSION_DISPLAY_CONFIG } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { getExperimentStatus } from '../experimentsLogic'
import { modalsLogic } from '../modalsLogic'
import { ExperimentDates } from './ExperimentDates'
import { StatsMethodModal } from './StatsMethodModal'
import { StatusTag } from './components'

export function Info(): JSX.Element {
    const {
        experiment,
        featureFlags,
        legacyPrimaryMetricsResults,
        legacySecondaryMetricsResults,
        primaryMetricsResults,
        secondaryMetricsResults,
        primaryMetricsResultsLoading,
        secondaryMetricsResultsLoading,
        statsMethod,
        usesNewQueryRunner,
        isExperimentDraft,
    } = useValues(experimentLogic)
    const { updateExperiment, refreshExperimentResults } = useActions(experimentLogic)
    const { openEditConclusionModal, openDescriptionModal, closeDescriptionModal, openStatsEngineModal } =
        useActions(modalsLogic)
    const { isDescriptionModalOpen } = useValues(modalsLogic)

    const [tempDescription, setTempDescription] = useState(experiment.description || '')

    useEffect(() => {
        setTempDescription(experiment.description || '')
    }, [experiment.description])

    const { created_by } = experiment

    if (!experiment.feature_flag) {
        return <></>
    }

    // Get the last refresh timestamp from either legacy or new results format
    // Check both primary and secondary metrics for the most recent timestamp
    const lastRefresh =
        legacyPrimaryMetricsResults?.[0]?.last_refresh ||
        legacySecondaryMetricsResults?.[0]?.last_refresh ||
        primaryMetricsResults?.[0]?.last_refresh ||
        secondaryMetricsResults?.[0]?.last_refresh

    return (
        <div>
            <div className="flex flex-wrap justify-between gap-4">
                <div className="deprecated-space-x-8 inline-flex">
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
                                            className="text-danger mr-1"
                                            fontSize="18px"
                                        />
                                    </Tooltip>
                                )}
                            <CopyToClipboardInline
                                iconStyle={{ color: 'var(--lemon-button-icon-opacity)' }}
                                className="text-sm font-normal"
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
                        <div className="deprecated-space-x-2 inline-flex">
                            <span>{statsMethod === ExperimentStatsMethod.Bayesian ? 'Bayesian' : 'Frequentist'}</span>
                            {usesNewQueryRunner &&
                                (isExperimentDraft ||
                                    featureFlags[FEATURE_FLAGS.EXPERIMENTS_DEV_STATS_METHOD_TOGGLE]) && (
                                    <>
                                        <LemonButton
                                            type="secondary"
                                            size="xsmall"
                                            onClick={() => {
                                                openStatsEngineModal()
                                            }}
                                            icon={<IconGear />}
                                            tooltip="Change stats engine"
                                        />
                                        <StatsMethodModal />
                                    </>
                                )}
                        </div>
                    </div>
                </div>

                <div className="flex flex-col">
                    <div className="deprecated-space-x-8 inline-flex">
                        {experiment.start_date && (
                            <div className="block">
                                <div className="text-xs font-semibold uppercase tracking-wide">Last refreshed</div>
                                <div className="deprecated-space-x-2 inline-flex">
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
                                        {primaryMetricsResultsLoading || secondaryMetricsResultsLoading
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
            <div className="mt-4 block">
                <div className="flex gap-6">
                    <div className="w-[500px]">
                        <div className="flex items-center gap-2">
                            <div className="text-xs font-semibold uppercase tracking-wide">Hypothesis</div>
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                icon={<IconPencil />}
                                onClick={openDescriptionModal}
                            />
                        </div>
                        {experiment.description ? (
                            <p className="m-0 py-2">{experiment.description}</p>
                        ) : (
                            <p className="text-muted m-0 py-2">Add your hypothesis for this test</p>
                        )}

                        <LemonModal
                            isOpen={isDescriptionModalOpen}
                            onClose={closeDescriptionModal}
                            title="Edit hypothesis"
                            footer={
                                <div className="flex items-center justify-end gap-2">
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
                    {experiment.conclusion && experiment.end_date && (
                        <div className="w-[500px]">
                            <div className="flex items-center gap-2">
                                <div className="text-xs font-semibold uppercase tracking-wide">Conclusion</div>
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    icon={<IconPencil />}
                                    onClick={openEditConclusionModal}
                                />
                            </div>
                            <div className="py-2">
                                <div className="flex items-center gap-2 font-semibold">
                                    <div
                                        className={clsx(
                                            'h-2 w-2 rounded-full',
                                            CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]?.color || ''
                                        )}
                                    />
                                    <span>
                                        {CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]?.title ||
                                            experiment.conclusion}
                                    </span>
                                </div>
                                <div>{experiment.conclusion_comment}</div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
