import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { notebookNodeLogic } from 'scenes/notebooks/Nodes/notebookNodeLogic'
import { defineNotebookWidgetViews } from 'scenes/notebooks/notebookWidgetCatalog'
import { NotebookNodeProps } from 'scenes/notebooks/types'

import { FeatureFlagType } from '~/types'

import { FeatureFlagCodeExample } from './FeatureFlagCodeExample'
import { FeatureFlagLogicProps, featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'

export type FeatureFlagNotebookWidgetAttributes = {
    id: FeatureFlagLogicProps['id']
    view?: string
}

type LoadedFeatureFlagWidgetProps = {
    featureFlag: FeatureFlagType
}

function FeatureFlagWidgetLoading(): JSX.Element {
    return (
        <div className="p-3">
            <LemonSkeleton className="h-6 flex-1" />
        </div>
    )
}

function FeatureFlagNotebookMetadata({ attributes }: NotebookNodeProps<FeatureFlagNotebookWidgetAttributes>): null {
    const { id, view } = attributes
    const logic = featureFlagLogic({ id })
    const { featureFlag, featureFlagActiveUpdateLoading } = useValues(logic)
    const { toggleFeatureFlagActive } = useActions(logic)
    const { isEditable } = useValues(notebookNodeLogic)
    const { setMenuItems, setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)

    useEffect(() => {
        if (!featureFlag.key) {
            setMenuItems(null)
            setTitlePlaceholder('Feature flag')
            setTitleStatus(null)
            return
        }

        const canToggle = view === 'editor' && featureFlag.can_edit
        setMenuItems(
            isEditable && featureFlag.can_edit
                ? [
                      {
                          label: featureFlag.active ? 'Disable feature flag' : 'Enable feature flag',
                          disabledReason: featureFlagActiveUpdateLoading ? 'Updating feature flag' : undefined,
                          onClick: () => toggleFeatureFlagActive(!featureFlag.active),
                      },
                  ]
                : null
        )
        setTitlePlaceholder(featureFlag.key)
        setTitleStatus({
            label: featureFlag.active ? 'Enabled' : 'Disabled',
            type: featureFlag.active ? 'success' : 'default',
            loading: featureFlagActiveUpdateLoading,
            onClick: canToggle ? () => toggleFeatureFlagActive(!featureFlag.active) : undefined,
            tooltip: canToggle ? (featureFlag.active ? 'Disable feature flag' : 'Enable feature flag') : undefined,
        })
    }, [
        featureFlag.active,
        featureFlag.can_edit,
        featureFlag.key,
        featureFlagActiveUpdateLoading,
        isEditable,
        setMenuItems,
        setTitlePlaceholder,
        setTitleStatus,
        toggleFeatureFlagActive,
        view,
    ])

    return null
}

export function withFeatureFlagNotebookMetadata(
    ViewComponent: (props: NotebookNodeProps<FeatureFlagNotebookWidgetAttributes>) => JSX.Element | null
): (props: NotebookNodeProps<FeatureFlagNotebookWidgetAttributes>) => JSX.Element {
    return function FeatureFlagNotebookViewWithMetadata(
        props: NotebookNodeProps<FeatureFlagNotebookWidgetAttributes>
    ): JSX.Element {
        return (
            <>
                <FeatureFlagNotebookMetadata {...props} />
                <ViewComponent {...props} />
            </>
        )
    }
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
            {featureFlag.name ? <span className="min-w-48 flex-1 truncate">{featureFlag.name}</span> : null}
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
        featureFlagLoading,
        featureFlagMissing,
        hasUnsavedChanges,
        nonEmptyVariants,
        hasEarlyAccessFeatures,
    } = useValues(logic)
    const { loadFeatureFlag, setFeatureFlagFilters, submitFeatureFlagWithValidation } = useActions(logic)

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
                        hasEarlyAccessFeatures={hasEarlyAccessFeatures}
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

export const FEATURE_FLAG_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<
    FeatureFlagNotebookWidgetAttributes,
    'FeatureFlag'
>('FeatureFlag', {
    summary: withFeatureFlagNotebookMetadata(FeatureFlagCompactSummary),
    editor: withFeatureFlagNotebookMetadata(FeatureFlagCompactEditor),
    conditions: withFeatureFlagNotebookMetadata(FeatureFlagReleaseConditionsWidget),
    implementation: withFeatureFlagNotebookMetadata(FeatureFlagImplementationWidget),
})
