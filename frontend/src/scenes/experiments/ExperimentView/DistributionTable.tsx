import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconFlag, IconLock } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonModal,
    LemonSwitch,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { AuthorizedUrlList } from '~/lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from '~/lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { useFeatureFlag } from '~/lib/hooks/useFeatureFlag'
import { IconOpenInApp } from '~/lib/lemon-ui/icons'
import {
    useVariantDistributionValidation,
    VariantDistributionEditor,
} from '~/scenes/experiments/ExperimentForm/VariantDistributionEditor'
import { experimentLogic } from '~/scenes/experiments/experimentLogic'
import { modalsLogic } from '~/scenes/experiments/modalsLogic'
import { getExperimentVariants } from '~/scenes/experiments/utils'
import { MultivariateFlagVariant } from '~/types'

import { HoldoutSelector } from './HoldoutSelector'
import { VariantNotes } from './VariantNotes'
import { VariantScreenshot } from './VariantScreenshot'
import { VariantTag } from './VariantTag'

export function DistributionModal(): JSX.Element {
    const { experiment, experimentLoading } = useValues(experimentLogic)
    const { updateDistribution } = useActions(experimentLogic)
    const { closeDistributionModal } = useActions(modalsLogic)
    const { isDistributionModalOpen } = useValues(modalsLogic)

    const [variants, setVariants] = useState<MultivariateFlagVariant[]>([])
    const [rolloutPercentage, setRolloutPercentage] = useState(100)
    const { areVariantRolloutsValid } = useVariantDistributionValidation(variants)

    const flagVariants = getExperimentVariants(experiment)

    // Initialize local state only when the modal transitions from closed to open.
    // Intentionally omit experiment data from deps so auto-refresh doesn't clobber edits.
    useEffect(() => {
        if (isDistributionModalOpen) {
            setVariants(flagVariants)
            setRolloutPercentage(experiment.feature_flag?.filters?.groups?.[0]?.rollout_percentage ?? 100)
        }
    }, [isDistributionModalOpen, flagVariants, experiment.feature_flag?.filters?.groups])

    const handleClose = (): void => {
        closeDistributionModal()
    }

    const handleSave = (): void => {
        updateDistribution(variants, rolloutPercentage)
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
                    of how changes will affect your experiment.{' '}
                    <Link to="https://posthog.com/docs/experiments/changing-distribution-after-rollout" target="_blank">
                        Read more
                    </Link>
                </LemonBanner>

                <VariantDistributionEditor
                    variants={variants}
                    onVariantsChange={setVariants}
                    rolloutPercentage={rolloutPercentage}
                    onRolloutPercentageChange={setRolloutPercentage}
                />

                <HoldoutSelector />
            </div>
        </LemonModal>
    )
}

export function DistributionTable(): JSX.Element {
    const { openDistributionModal } = useActions(modalsLogic)
    const { experiment, excludedVariants, experimentUpdateLoading } = useValues(experimentLogic)
    const { reportExperimentReleaseConditionsViewed, setVariantExcluded } = useActions(experimentLogic)

    const excludedVariantsEnabled = useFeatureFlag('EXPERIMENTS_EXCLUDED_VARIANTS')

    /**
     * This is future-proofing to match the experiment query runner backend, that uses
     * the baseline variant key to determine the baseline variant.
     */
    const baselineKey = experiment.stats_config?.baseline_variant_key || 'control'
    const variants = getExperimentVariants(experiment)

    /**
     * We use this check to disable the toggle if there's only one test variant left.
     * - not the baseline variant
     * - not excluded
     */
    const hasOnlyOneTestVariant =
        variants.filter(({ key }) => key !== baselineKey && !excludedVariants.includes(key)).length <= 1

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
    // Keep every column the same width: base columns (Variant, Split, Screenshot, Notes)
    // plus the optional Analysis and web Preview columns.
    const columnCount = 4 + (excludedVariantsEnabled ? 1 : 0) + (experiment?.type === 'web' ? 1 : 0)
    const className = { 4: 'w-1/4', 5: 'w-1/5', 6: 'w-1/6' }[columnCount] ?? 'w-1/4'
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
        ...(excludedVariantsEnabled
            ? [
                  {
                      className,
                      key: 'analysis',
                      title: 'Include in analysis',
                      tooltip:
                          'Toggle off to exclude a variant from metric results. Excluded variants are still served to users but omitted from statistical analysis.',
                      render: function Analysis(_, { key }): JSX.Element {
                          /**
                           * bail early for holdouts
                           */
                          if (key === `holdout-${experiment.holdout?.id}`) {
                              return <span className="text-muted">-</span>
                          }
                          /**
                           * bail early for baseline variant
                           */
                          if (key === baselineKey) {
                              return (
                                  <LemonTag type="muted" icon={<IconLock />}>
                                      Baseline
                                  </LemonTag>
                              )
                          }
                          const excluded = excludedVariants.includes(key)
                          /**
                           * we disable the toggle if:
                           * - the variant is not excluded: we have to allow re-including it
                           * - there's only one variant left when we remove the baseline
                           */
                          const disableToggle = !excluded && hasOnlyOneTestVariant
                          return (
                              <div className="flex items-center gap-2">
                                  <LemonSwitch
                                      checked={!excluded}
                                      onChange={(checked) => setVariantExcluded(key, !checked)}
                                      disabledReason={
                                          disableToggle
                                              ? 'At least one test variant must remain in analysis'
                                              : undefined
                                      }
                                      loading={experimentUpdateLoading}
                                  />
                                  {excluded && <LemonTag type="warning">Excluded</LemonTag>}
                              </div>
                          )
                      },
                  } as LemonTableColumns<MultivariateFlagVariant>[number],
              ]
            : []),
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
        {
            className: className,
            key: 'variant_notes',
            title: 'Notes',
            render: function Key(_, item): JSX.Element {
                if (item.key === `holdout-${experiment.holdout?.id}`) {
                    return <div className="h-16" />
                }
                return <VariantNotes variantKey={item.key} />
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

    const variantData = getExperimentVariants(experiment).map((variant) => ({
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
            {excludedVariants.length > 0 && hasOnlyOneTestVariant && (
                <LemonBanner type="warning" className="mb-4">
                    At least one test variant must remain in analysis. Re-include a variant to exclude others.
                </LemonBanner>
            )}
            <LemonTable
                loading={false}
                columns={columns}
                dataSource={tableData}
                rowClassName={(item) => {
                    if (item.key === `holdout-${experiment.holdout?.id}`) {
                        return 'dark:bg-fill-primary bg-mid'
                    }
                    if (excludedVariants.includes(item.key)) {
                        return 'bg-fill-tertiary'
                    }
                    return ''
                }}
            />
        </div>
    )
}
