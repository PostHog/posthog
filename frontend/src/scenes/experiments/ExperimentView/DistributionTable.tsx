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
import { getBaselineVariantKey, getExperimentVariants } from '~/scenes/experiments/utils'
import { Experiment, MultivariateFlagVariant } from '~/types'

import { HoldoutSelector } from './HoldoutSelector'
import { VariantNotes } from './VariantNotes'
import { VariantScreenshot } from './VariantScreenshot'
import { VariantTag } from './VariantTag'

export function useDistributionModal(): {
    isOpen: boolean
    close: () => void
    save: () => void
    loading: boolean
    saveDisabledReason?: string
    variants: MultivariateFlagVariant[]
    setVariants: (variants: MultivariateFlagVariant[]) => void
    rolloutPercentage: number
    setRolloutPercentage: (value: number) => void
} {
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

    return {
        isOpen: isDistributionModalOpen,
        close: closeDistributionModal,
        save: () => {
            updateDistribution(variants, rolloutPercentage)
            closeDistributionModal()
        },
        loading: experimentLoading,
        saveDisabledReason: !areVariantRolloutsValid ? 'Percentage splits must sum to 100' : undefined,
        variants,
        setVariants,
        rolloutPercentage,
        setRolloutPercentage,
    }
}

export function DistributionModal(): JSX.Element {
    const {
        isOpen: isDistributionModalOpen,
        close: handleClose,
        save: handleSave,
        loading: experimentLoading,
        saveDisabledReason,
        variants,
        setVariants,
        rolloutPercentage,
        setRolloutPercentage,
    } = useDistributionModal()

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
                        disabledReason={saveDisabledReason}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <LemonBanner type="info">
                    {DISTRIBUTION_CHANGE_WARNING}{' '}
                    <Link to={DISTRIBUTION_DOCS_URL} target="_blank">
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

export const DISTRIBUTION_EXCLUDE_HELP =
    'Toggle off to exclude a variant from metric results. Excluded variants are still served to users but omitted from statistical analysis.'
export const DISTRIBUTION_LAST_VARIANT_REASON = 'At least one test variant must remain in analysis'
export const DISTRIBUTION_LAST_VARIANT_WARNING =
    'At least one test variant must remain in analysis. Re-include a variant to exclude others.'
export const DISTRIBUTION_CHANGE_WARNING =
    "Adjusting variant distribution may impact the validity of your results. Adjust only if you're aware of how changes will affect your experiment."
export const DISTRIBUTION_DOCS_URL = 'https://posthog.com/docs/experiments/changing-distribution-after-rollout'
export const PREVIEW_DOMAIN_TITLE = 'Select a domain'
export const PREVIEW_DOMAIN_DESCRIPTION = 'Choose the domain on which to preview this experiment variant'

export function holdoutNote(percentage: number | null | undefined): string {
    return `This experiment has a holdout group of ${percentage ?? ''}%. The variants are modified to show their relative rollout percentage.`
}

export function previewQuery(experimentId: number | string | undefined, variant: string): string {
    return '?__experiment_id=' + experimentId + '&__experiment_variant=' + variant
}

export interface DistributionTableModel {
    experiment: Experiment
    baselineKey: string
    excludedVariants: string[]
    excludedVariantsEnabled: boolean
    hasOnlyOneTestVariant: boolean
    holdoutKey: string | null
    tableData: MultivariateFlagVariant[]
    experimentUpdateLoading: boolean
    setVariantExcluded: (key: string, excluded: boolean) => void
    openDistribution: () => void
}

export function useDistributionTable(): DistributionTableModel {
    const { openDistributionModal } = useActions(modalsLogic)
    const { experiment, excludedVariants, experimentUpdateLoading } = useValues(experimentLogic)
    const { reportExperimentReleaseConditionsViewed, setVariantExcluded } = useActions(experimentLogic)
    const excludedVariantsEnabled = useFeatureFlag('EXPERIMENTS_EXCLUDED_VARIANTS')

    const baselineKey = getBaselineVariantKey(experiment)
    const variants = getExperimentVariants(experiment)
    const holdoutData = experiment.holdout
        ? [
              {
                  key: `holdout-${experiment.holdout.id}`,
                  rollout_percentage: experiment.holdout.filters[0].rollout_percentage,
              } as MultivariateFlagVariant,
          ]
        : []
    const variantData = variants.map((variant) => ({
        ...variant,
        rollout_percentage:
            variant.rollout_percentage * ((100 - (experiment.holdout?.filters[0].rollout_percentage || 0)) / 100),
    }))

    return {
        experiment,
        baselineKey,
        excludedVariants,
        excludedVariantsEnabled,
        /**
         * We use this check to disable the toggle if there's only one test variant left.
         * - not the baseline variant
         * - not excluded
         */
        hasOnlyOneTestVariant:
            variants.filter(({ key }) => key !== baselineKey && !excludedVariants.includes(key)).length <= 1,
        holdoutKey: experiment.holdout ? `holdout-${experiment.holdout.id}` : null,
        tableData: [...variantData, ...holdoutData],
        experimentUpdateLoading,
        setVariantExcluded,
        openDistribution: () => {
            openDistributionModal()
            reportExperimentReleaseConditionsViewed(experiment.id)
        },
    }
}

export function DistributionTable(): JSX.Element {
    const {
        experiment,
        baselineKey,
        excludedVariants,
        excludedVariantsEnabled,
        hasOnlyOneTestVariant,
        tableData,
        experimentUpdateLoading,
        setVariantExcluded,
        openDistribution,
    } = useDistributionTable()

    const onSelectElement = (variant: string): void => {
        LemonDialog.open({
            title: PREVIEW_DOMAIN_TITLE,
            description: PREVIEW_DOMAIN_DESCRIPTION,
            content: (
                <>
                    <AuthorizedUrlList
                        query={previewQuery(experiment?.id, variant)}
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
                      tooltip: DISTRIBUTION_EXCLUDE_HELP,
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
                                      disabledReason={disableToggle ? DISTRIBUTION_LAST_VARIANT_REASON : undefined}
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
                            onClick={openDistribution}
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
                    {holdoutNote(experiment.holdout.filters[0].rollout_percentage)}
                </LemonBanner>
            )}
            {excludedVariants.length > 0 && hasOnlyOneTestVariant && (
                <LemonBanner type="warning" className="mb-4">
                    {DISTRIBUTION_LAST_VARIANT_WARNING}
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
