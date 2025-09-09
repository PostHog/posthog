import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconGear, IconPencil, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal, Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ExperimentStatsMethod, ProgressStatus } from '~/types'

import { CONCLUSION_DISPLAY_CONFIG } from '../constants'
import { experimentLogic } from '../experimentLogic'
import { getExperimentStatus } from '../experimentsLogic'
import { modalsLogic } from '../modalsLogic'
import { ExperimentDuration } from './ExperimentDuration'
import { StatsMethodModal } from './StatsMethodModal'
import { StatusTag } from './components'

export const ExperimentLastRefresh = ({
    isRefreshing,
    lastRefresh,
    onClick,
}: {
    isRefreshing: boolean
    lastRefresh: string
    onClick: () => void
}): JSX.Element => {
    usePeriodicRerender(15000) // Re-render every 15 seconds for up-to-date last refresh time

    return (
        <div className="flex flex-col">
            <Label intent="menu">Last refreshed</Label>
            <div className="inline-flex deprecated-space-x-2">
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
                    {isRefreshing ? 'Loading…' : lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
                </span>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={onClick}
                    data-attr="refresh-experiment"
                    icon={<IconRefresh />}
                    tooltip="Refresh experiment results"
                />
            </div>
        </div>
    )
}

export function Info(): JSX.Element {
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
        experimentLoading,
        isExperimentDraft,
    } = useValues(experimentLogic)
    const { updateExperiment, refreshExperimentResults } = useActions(experimentLogic)
    const { openEditConclusionModal, openDescriptionModal, closeDescriptionModal, openStatsEngineModal } =
        useActions(modalsLogic)
    const { isDescriptionModalOpen } = useValues(modalsLogic)

    const [tempDescription, setTempDescription] = useState(experiment.description || '')
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

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
        <SceneContent>
            <SceneTitleSection
                name={experiment?.name}
                description={null}
                resourceType={{
                    type: 'experiment',
                }}
                isLoading={experimentLoading}
                onNameChange={(name) => updateExperiment({ name })}
                onDescriptionChange={(description) => updateExperiment({ description })}
                canEdit
                forceEdit
                renameDebounceMs={1000}
            />
            <SceneDivider />
            <div className="grid gap-2 overflow-hidden grid-cols-1 min-[1200px]:grid-cols-[1fr_26rem]">
                {/* Column 1 */}
                <div className="flex flex-col gap-0 overflow-hidden">
                    {/* Row 1: Status, Feature flag, Stats engine */}
                    <div className="inline-flex deprecated-space-x-8">
                        <div className="flex flex-col" data-attr="experiment-status">
                            <Label intent="menu">Status</Label>
                            <StatusTag status={status} />
                        </div>
                        {experiment.feature_flag && (
                            <div className="flex flex-col">
                                <Label intent="menu">Feature flag</Label>
                                <div className="flex gap-1 items-center">
                                    {status === ProgressStatus.Running && !experiment.feature_flag.active && (
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
                            <Label intent="menu">Stats Engine</Label>
                            <div className="inline-flex deprecated-space-x-2">
                                <span>
                                    {statsMethod === ExperimentStatsMethod.Bayesian ? 'Bayesian' : 'Frequentist'}
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
                                            tooltip="Change stats engine"
                                        />
                                        <StatsMethodModal />
                                    </>
                                )}
                            </div>
                        </div>
                    </div>

                    <div className="w-[500px]">
                        <div className="flex items-center gap-2">
                            <Label intent="menu">Hypothesis</Label>
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                icon={<IconPencil />}
                                onClick={openDescriptionModal}
                            />
                        </div>
                        {experiment.description ? (
                            <p className={cn('py-2 m-0', newSceneLayout && 'py-0')}>{experiment.description}</p>
                        ) : (
                            <p className={cn('py-2 m-0 text-secondary', newSceneLayout && 'py-0')}>
                                Add your hypothesis for this test
                            </p>
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
                <div className="flex flex-col gap-4 overflow-hidden items-start min-[1200px]:items-end">
                    {/* Row 1: Duration */}
                    {!isExperimentDraft && <ExperimentDuration />}

                    {/* Row 2: Last refreshed, Created by */}
                    <div className="flex flex-col overflow-hidden items-start min-[1200px]:items-end">
                        <div className="inline-flex deprecated-space-x-8">
                            {experiment.start_date && (
                                <ExperimentLastRefresh
                                    isRefreshing={primaryMetricsResultsLoading || secondaryMetricsResultsLoading}
                                    lastRefresh={lastRefresh}
                                    onClick={() => refreshExperimentResults(true)}
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
            <div className={cn('block mt-4', newSceneLayout && 'mt-0')}>
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
                            <div className={cn('py-2', newSceneLayout && 'py-0')}>
                                <div className="font-semibold flex items-center gap-2">
                                    <div
                                        className={clsx(
                                            'w-2 h-2 rounded-full',
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
        </SceneContent>
    )
}
