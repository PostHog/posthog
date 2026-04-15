import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconFlag } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IconOpenInApp } from 'lib/lemon-ui/icons'

import { MultivariateFlagVariant } from '~/types'

import {
    useVariantDistributionValidation,
    VariantDistributionEditor,
} from '../ExperimentForm/VariantDistributionEditor'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { VariantTag } from './components'
import { HoldoutSelector } from './HoldoutSelector'
import { VariantScreenshot } from './VariantScreenshot'

export function DistributionModal(): JSX.Element {
    const { experiment, experimentLoading } = useValues(experimentLogic)
    const { updateDistribution } = useActions(experimentLogic)
    const { closeDistributionModal } = useActions(modalsLogic)
    const { isDistributionModalOpen } = useValues(modalsLogic)

    const [variants, setVariants] = useState<MultivariateFlagVariant[]>([])
    const { areVariantRolloutsValid } = useVariantDistributionValidation(variants)

    // Initialize local state only when the modal transitions from closed to open.
    // Intentionally omit experiment data from deps so auto-refresh doesn't clobber edits.
    useEffect(() => {
        if (isDistributionModalOpen) {
            setVariants(experiment.feature_flag?.filters?.multivariate?.variants || [])
        }
    }, [isDistributionModalOpen, experiment.feature_flag?.filters?.multivariate?.variants])

    const handleClose = (): void => {
        closeDistributionModal()
    }

    const handleSave = (): void => {
        if (!experiment.feature_flag) {
            return
        }
        // FeatureFlagBasicType has all fields updateDistribution needs (id, filters)
        updateDistribution({
            ...experiment.feature_flag,
            filters: {
                ...experiment.feature_flag.filters,
                multivariate: {
                    ...experiment.feature_flag.filters.multivariate,
                    variants,
                },
            },
        } as any)
        closeDistributionModal()
    }

    return (
        <LemonModal
            isOpen={isDistributionModalOpen}
            onClose={handleClose}
            width={600}
            title="Change experiment distribution"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={handleSave}
                        type="primary"
                        loading={experimentLoading}
                        disabled={!areVariantRolloutsValid}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <LemonBanner type="info">
                    Adjusting variant distribution may impact the validity of your results. Adjust only if you're aware
                    of how changes will affect your experiment.
                </LemonBanner>

                <VariantDistributionEditor
                    variants={variants}
                    onVariantsChange={setVariants}
                    rolloutPercentage={experiment.feature_flag?.filters?.groups?.[0]?.rollout_percentage ?? 100}
                />

                <HoldoutSelector />
            </div>
        </LemonModal>
    )
}

export function DistributionTable(): JSX.Element {
    const { openDistributionModal } = useActions(modalsLogic)
    const { experiment } = useValues(experimentLogic)
    const { reportExperimentReleaseConditionsViewed } = useActions(experimentLogic)

    const onSelectElement = (variant: string): void => {
        LemonDialog.open({
            title: 'Select a domain',
            description: 'Choose the domain on which to preview this experiment variant',
            content: (
                <>
                    <AuthorizedUrlList
                        query={'?__experiment_id=' + experiment?.id + '&__experiment_variant=' + variant}
                        experimentId={experiment?.id}
                        type={AuthorizedUrlListType.WEB_EXPERIMENTS}
                    />
                </>
            ),
            primaryButton: {
                children: 'Close',
                type: 'secondary',
            },
        })
    }
    const className = experiment?.type === 'web' ? 'w-1/2.5' : 'w-1/3'
    const columns: LemonTableColumns<MultivariateFlagVariant> = [
        {
            className: className,
            key: 'key',
            title: 'Variant',
            render: function Key(_, item): JSX.Element {
                return <VariantTag variantKey={item.key} />
            },
        },
        {
            className: className,
            key: 'rollout_percentage',
            title: 'Split',
            render: function Key(_, item): JSX.Element {
                return <div>{`${item.rollout_percentage}%`}</div>
            },
        },
        {
            className: className,
            key: 'variant_screenshot',
            title: 'Screenshot',
            render: function Key(_, item): JSX.Element {
                if (item.key === `holdout-${experiment.holdout?.id}`) {
                    return <div className="h-16" />
                }
                return (
                    <div className="my-2">
                        <VariantScreenshot variantKey={item.key} rolloutPercentage={item.rollout_percentage} />
                    </div>
                )
            },
        },
    ]

    if (experiment.type === 'web') {
        columns.push({
            className: className,
            key: 'preview_web_experiment',
            title: 'Preview',
            render: function Key(_, item): JSX.Element {
                return (
                    <div className="my-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={(e) => {
                                e.preventDefault()
                                onSelectElement(item.key)
                            }}
                            sideIcon={<IconOpenInApp />}
                        >
                            Preview variant
                        </LemonButton>
                    </div>
                )
            },
        })
    }

    const holdoutData = experiment.holdout
        ? [
              {
                  key: `holdout-${experiment.holdout.id}`,
                  rollout_percentage: experiment.holdout.filters[0].rollout_percentage,
              } as MultivariateFlagVariant,
          ]
        : []

    const variantData = (experiment.feature_flag?.filters.multivariate?.variants || []).map((variant) => ({
        ...variant,
        rollout_percentage:
            variant.rollout_percentage * ((100 - (experiment.holdout?.filters[0].rollout_percentage || 0)) / 100),
    }))

    const tableData = [...variantData, ...holdoutData]

    return (
        <div>
            <div className="flex">
                <div className="w-1/2">
                    <h2 className="font-semibold text-lg">Distribution</h2>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto mb-2">
                        <LemonButton
                            icon={<IconFlag />}
                            onClick={() => {
                                openDistributionModal()
                                reportExperimentReleaseConditionsViewed(experiment.id)
                            }}
                            type="secondary"
                            size="xsmall"
                            className="font-semibold"
                        >
                            Manage distribution
                        </LemonButton>
                    </div>
                </div>
            </div>
            {experiment.holdout && (
                <LemonBanner type="info" className="mb-4">
                    This experiment has a holdout group of {experiment.holdout.filters[0].rollout_percentage}%. The
                    variants are modified to show their relative rollout percentage.
                </LemonBanner>
            )}
            <LemonTable
                loading={false}
                columns={columns}
                dataSource={tableData}
                rowClassName={(item) =>
                    item.key === `holdout-${experiment.holdout?.id}` ? 'dark:bg-fill-primary bg-mid' : ''
                }
            />
        </div>
    )
}
