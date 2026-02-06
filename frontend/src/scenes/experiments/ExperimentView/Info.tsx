import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconGear, IconPencil, IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTag, Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { ExperimentProgressStatus, ExperimentStatsMethod } from '~/types'

import { CONCLUSION_DISPLAY_CONFIG } from '../constants'
import { experimentLogic } from '../experimentLogic'
import type { ExperimentSceneLogicProps } from '../experimentSceneLogic'
import { getExperimentStatus } from '../experimentsLogic'
import { modalsLogic } from '../modalsLogic'
import { ExperimentDuration } from './ExperimentDuration'
import { ExperimentReloadAction } from './ExperimentReloadAction'
import { RunningTimeNew } from './RunningTimeNew'
import { StatsMethodModal } from './StatsMethodModal'
import { StatusTag } from './components'

export function Info({ tabId }: Pick<ExperimentSceneLogicProps, 'tabId'>): JSX.Element {
    const {
        experiment,
        legacyPrimaryMetricsResults,
        legacySecondaryMetricsResults,
        primaryMetricsResults,
        secondaryMetricsResults,
        primaryMetricsResultsLoading,
        secondaryMetricsResultsLoading,
        statsMethod,
        usesNewQueryRunner,
        isExperimentDraft,
        isSingleVariantShipped,
        shippedVariantKey,
        autoRefresh,
    } = useValues(experimentLogic)
    const { updateExperiment, refreshExperimentResults, reportExperimentMetricsRefreshed } = useActions(experimentLogic)
    const {
        openEditConclusionModal,
        openDescriptionModal,
        closeDescriptionModal,
        openStatsEngineModal,
        openRunningTimeConfigModal,
    } = useActions(modalsLogic)
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

    const status = getExperimentStatus(experiment)

    return (
        <>
            <div className="grid gap-2 overflow-hidden grid-cols-1 min-[1400px]:grid-cols-[2fr_3fr]">
                {/* Column 1 */}
                <div className="flex flex-col gap-0 overflow-hidden min-w-0">
                    {/* Row 1: Status, Feature flag, Stats engine */}
                    <div className="flex flex-wrap gap-x-8 gap-y-2">
                        <div className="flex flex-col" data-attr="experiment-status">
                            <Label intent="menu">Status</Label>
                            <div className="flex gap-1">
                                {status === ExperimentProgressStatus.Paused ? (
                                    <Tooltip
                                        placement="bottom"
                                        title="Your experiment is paused. The linked flag is disabled and no data is being collected."
                                    >
                                        <StatusTag status={status} />
                                    </Tooltip>
                                ) : (
                                    <StatusTag status={status} />
                                )}
                                {isSingleVariantShipped && (
                                    <Tooltip
                                        title={`Variant "${shippedVariantKey}" has been rolled out to 100% of users`}
                                    >
                                        <LemonTag type="completion" className="cursor-default">
                                            <b className="uppercase">100% rollout</b>
                                        </LemonTag>
                                    </Tooltip>
                                )}
                            </div>
                        </div>
                        {experiment.feature_flag && (
                            <div className="flex flex-col max-w-[500px]">
                                <Label intent="menu">Feature flag</Label>
                                <div className="flex gap-1 items-center">
                                    {status === ExperimentProgressStatus.Paused && (
                                        <Tooltip
                                            placement="bottom"
                                            title="Your experiment is paused. The linked flag is disabled and no data is being collected."
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
                                        to={
                                            experiment.feature_flag
                                                ? urls.featureFlag(experiment.feature_flag.id)
                                                : undefined
                                        }
                                    >
                                        <IconOpenInNew fontSize="18" />
                                    </Link>
                                </div>
                            </div>
                        )}
                        <div className="flex flex-col">
                            <Label intent="menu">Statistics</Label>
                            <div className="inline-flex deprecated-space-x-2">
                                <span>
                                    {statsMethod === ExperimentStatsMethod.Bayesian ? 'Bayesian' : 'Frequentist'}
                                    {' / '}
                                    {statsMethod === ExperimentStatsMethod.Bayesian
                                        ? `${((experiment.stats_config?.bayesian?.ci_level ?? 0.95) * 100).toFixed(0)}%`
                                        : `${((1 - (experiment.stats_config?.frequentist?.alpha ?? 0.05)) * 100).toFixed(0)}%`}
                                </span>
                                {usesNewQueryRunner && (
                                    <>
                                        <LemonButton
                                            type="secondary"
                                            size="xsmall"
                                            onClick={() => {
                                                openStatsEngineModal()
                                            }}
                                            icon={<IconGear />}
                                            tooltip="Configure statistics"
                                        />
                                        <StatsMethodModal />
                                    </>
                                )}
                            </div>
                        </div>
                    </div>

                    <div className="w-[500px]">
                        <div className="flex items-center gap-2 mt-2">
                            <Label intent="menu">Hypothesis</Label>
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                icon={<IconPencil />}
                                onClick={openDescriptionModal}
                            />
                        </div>
                        {experiment.description ? (
                            <p className={cn('m-0 mt-2')}>{experiment.description}</p>
                        ) : (
                            <p className={cn('m-0 mt-2 text-secondary italic')}>Add your hypothesis for this test</p>
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
                                placeholder="Add your hypothesis for this test"
                                minRows={6}
                                maxLength={400}
                            />
                        </LemonModal>
                    </div>
                </div>

                {/* Column 2 */}
                <div className="flex flex-col gap-4 overflow-hidden items-start min-[1400px]:items-end min-w-0">
                    {/* Row 1: Duration (date pickers) - only for launched experiments */}
                    {!isExperimentDraft && <ExperimentDuration />}

                    {/* Row 2: Running time, Last refreshed, Created by */}
                    <div className="flex flex-col overflow-hidden items-start min-[1400px]:items-end">
                        <div className="flex flex-wrap gap-x-8 gap-y-2 justify-end">
                            {tabId && (
                                <RunningTimeNew
                                    experiment={experiment}
                                    tabId={tabId}
                                    onClick={openRunningTimeConfigModal}
                                    isExperimentDraft={isExperimentDraft}
                                />
                            )}
                            {experiment.start_date && (
                                <ExperimentReloadAction
                                    isRefreshing={primaryMetricsResultsLoading || secondaryMetricsResultsLoading}
                                    lastRefresh={lastRefresh}
                                    onClick={() => {
                                        // Track manual refresh click
                                        reportExperimentMetricsRefreshed(experiment, true, {
                                            triggered_by: 'manual',
                                            auto_refresh_enabled: autoRefresh.enabled,
                                            auto_refresh_interval: autoRefresh.interval,
                                        })
                                        refreshExperimentResults(true)
                                    }}
                                />
                            )}
                            <div className="flex flex-col">
                                <Label intent="menu">Created by</Label>
                                {created_by && <ProfilePicture user={created_by} size="md" showName />}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div className="flex gap-6">
                {experiment.conclusion && experiment.end_date && (
                    <div className="w-[500px]">
                        <div className="flex items-center gap-2">
                            <Label intent="menu">Conclusion</Label>
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                icon={<IconPencil />}
                                onClick={openEditConclusionModal}
                            />
                        </div>
                        <div>
                            <div className="font-semibold flex items-center gap-2">
                                <div
                                    className={clsx(
                                        'w-2 h-2 rounded-full',
                                        CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]?.color || ''
                                    )}
                                />
                                <span>
                                    {CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]?.title || experiment.conclusion}
                                </span>
                            </div>
                            <div>{experiment.conclusion_comment}</div>
                        </div>
                    </div>
                )}
            </div>
        </>
    )
}
