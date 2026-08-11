import { BindLogic, useActions, useValues } from 'kea'

import { IconFlag } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { NotebookNodeProps, PostHogWidgetViews } from 'scenes/notebooks/types'

import { FeatureFlagType } from '~/types'

import { FeatureFlagCodeExample } from './FeatureFlagCodeExample'
import { FeatureFlagLogicProps, featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'
import { FlagActiveToggleTag } from './FlagActiveToggleTag'

export type FeatureFlagNotebookWidgetAttributes = {
    id: FeatureFlagLogicProps['id']
    view?: string
}

type LoadedFeatureFlagWidgetProps = {
    featureFlag: FeatureFlagType
}

function FeatureFlagWidgetLoading(): JSX.Element {
    return (
        <div className="flex items-center gap-2 p-3">
            <IconFlag className="text-lg" />
            <LemonSkeleton className="h-6 flex-1" />
        </div>
    )
}

function FeatureFlagCompactSummary({
    attributes,
}: NotebookNodeProps<FeatureFlagNotebookWidgetAttributes>): JSX.Element {
    const { id } = attributes
    const { featureFlag, featureFlagLoading, featureFlagMissing } = useValues(featureFlagLogic({ id }))

    if (featureFlagMissing) {
        return <NotFound object="feature flag" />
    }
    if (featureFlagLoading && !featureFlag.id) {
        return <FeatureFlagWidgetLoading />
    }

    return (
        <BindLogic logic={featureFlagLogic} props={{ id }}>
            <FeatureFlagCompactSummaryContent featureFlag={featureFlag} />
        </BindLogic>
    )
}

function FeatureFlagCompactSummaryContent({ featureFlag }: LoadedFeatureFlagWidgetProps): JSX.Element {
    const conditionCount = featureFlag.filters.groups?.length ?? 0
    const variantCount = featureFlag.filters.multivariate?.variants?.length ?? 0
    const flagType = featureFlag.is_remote_configuration
        ? 'Remote config'
        : variantCount > 0
          ? 'Multivariate'
          : 'Boolean'

    return (
        <div className="flex flex-wrap items-center gap-2 p-3">
            <IconFlag className="text-lg shrink-0" />
            <div className="flex min-w-48 flex-1 flex-col">
                <span className="truncate font-semibold">{featureFlag.key}</span>
                {featureFlag.name ? <span className="truncate text-xs text-secondary">{featureFlag.name}</span> : null}
            </div>
            <FlagActiveToggleTag active={featureFlag.active} />
            <LemonTag type="muted">{flagType}</LemonTag>
            {!featureFlag.is_remote_configuration ? (
                <span className="text-xs text-secondary">
                    {conditionCount} release {conditionCount === 1 ? 'condition' : 'conditions'}
                </span>
            ) : null}
        </div>
    )
}

function FeatureFlagReleaseConditionsWidget({
    attributes,
}: NotebookNodeProps<FeatureFlagNotebookWidgetAttributes>): JSX.Element {
    const { id } = attributes
    const { featureFlag, featureFlagLoading, featureFlagMissing } = useValues(featureFlagLogic({ id }))

    if (featureFlagMissing) {
        return <NotFound object="feature flag" />
    }
    if (featureFlagLoading && !featureFlag.id) {
        return <FeatureFlagWidgetLoading />
    }

    return (
        <BindLogic logic={featureFlagLogic} props={{ id }}>
            <div className="p-3">
                {featureFlag.is_remote_configuration ? (
                    <div className="text-sm text-secondary">Remote config flags do not use release conditions.</div>
                ) : (
                    <FeatureFlagReleaseConditionsCollapsible id={String(id)} filters={featureFlag.filters} readOnly />
                )}
            </div>
        </BindLogic>
    )
}

function FeatureFlagImplementationWidget({
    attributes,
}: NotebookNodeProps<FeatureFlagNotebookWidgetAttributes>): JSX.Element {
    const { id } = attributes
    const { featureFlag, featureFlagLoading, featureFlagMissing } = useValues(featureFlagLogic({ id }))

    if (featureFlagMissing) {
        return <NotFound object="feature flag" />
    }
    if (featureFlagLoading && !featureFlag.id) {
        return <FeatureFlagWidgetLoading />
    }

    return (
        <BindLogic logic={featureFlagLogic} props={{ id }}>
            <div className="p-3">
                <FeatureFlagCodeExample featureFlag={featureFlag} />
            </div>
        </BindLogic>
    )
}

function FeatureFlagCompactEditor({ attributes }: NotebookNodeProps<FeatureFlagNotebookWidgetAttributes>): JSX.Element {
    const { id } = attributes
    const logic = featureFlagLogic({ id })
    const {
        featureFlag,
        featureFlagActiveUpdateLoading,
        featureFlagLoading,
        featureFlagMissing,
        hasUnsavedChanges,
        nonEmptyVariants,
    } = useValues(logic)
    const { loadFeatureFlag, setFeatureFlagFilters, submitFeatureFlagWithValidation, toggleFeatureFlagActive } =
        useActions(logic)

    if (featureFlagMissing) {
        return <NotFound object="feature flag" />
    }
    if (featureFlagLoading && !featureFlag.id) {
        return <FeatureFlagWidgetLoading />
    }

    const managedByExperiment = !!featureFlag.experiment_set?.length
    const editingDisabledReason = !featureFlag.can_edit
        ? "You only have view access to this feature flag. Contact the flag's creator to make changes."
        : managedByExperiment
          ? 'Release conditions are managed by the linked experiment.'
          : undefined

    return (
        <BindLogic logic={featureFlagLogic} props={{ id }}>
            <div className="flex flex-col gap-3 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                        <IconFlag className="text-lg shrink-0" />
                        <span className="truncate font-semibold">{featureFlag.key}</span>
                    </div>
                    <FlagActiveToggleTag
                        active={featureFlag.active}
                        toggling={featureFlagActiveUpdateLoading}
                        onToggle={featureFlag.can_edit ? toggleFeatureFlagActive : undefined}
                    />
                </div>

                {featureFlag.is_remote_configuration ? (
                    <div className="rounded border border-dashed p-3 text-sm text-secondary">
                        Open the feature flag to edit its remote config payload.
                    </div>
                ) : (
                    <FeatureFlagReleaseConditionsCollapsible
                        id={String(id)}
                        flagId={id}
                        filters={featureFlag.filters}
                        onChange={setFeatureFlagFilters}
                        readOnly={!!editingDisabledReason}
                        variants={nonEmptyVariants}
                        isDisabled={!featureFlag.active}
                        bucketingIdentifier={featureFlag.bucketing_identifier}
                        evaluationRuntime={featureFlag.evaluation_runtime}
                    />
                )}

                {!featureFlag.is_remote_configuration ? (
                    <div className="flex justify-end gap-2 border-t pt-3">
                        <LemonButton
                            type="secondary"
                            size="small"
                            loading={featureFlagLoading}
                            onClick={() => loadFeatureFlag()}
                            disabledReason={
                                editingDisabledReason ??
                                (!hasUnsavedChanges ? 'There are no unsaved changes.' : undefined)
                            }
                        >
                            Reset
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            loading={featureFlagLoading}
                            onClick={() => submitFeatureFlagWithValidation(featureFlag)}
                            disabledReason={
                                editingDisabledReason ??
                                (!hasUnsavedChanges ? 'There are no unsaved changes.' : undefined)
                            }
                        >
                            Save
                        </LemonButton>
                    </div>
                ) : null}
            </div>
        </BindLogic>
    )
}

export const FEATURE_FLAG_NOTEBOOK_WIDGET_VIEWS = {
    'compact-summary': {
        label: 'Compact summary',
        description: 'Show the flag status, type, and release condition count',
        Component: FeatureFlagCompactSummary,
    },
    'compact-editor': {
        label: 'Compact editor',
        description: 'Edit the flag status and release conditions in the notebook',
        Component: FeatureFlagCompactEditor,
    },
    'release-conditions': {
        label: 'Release conditions',
        description: 'Show the flag release conditions',
        Component: FeatureFlagReleaseConditionsWidget,
    },
    implementation: {
        label: 'Implementation',
        description: 'Show SDK implementation instructions',
        Component: FeatureFlagImplementationWidget,
    },
} satisfies PostHogWidgetViews<FeatureFlagNotebookWidgetAttributes>
