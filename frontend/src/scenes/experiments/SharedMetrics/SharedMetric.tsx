import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonLabel, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { tagsModel } from '~/models/tagsModel'
import { ExperimentMetric, NodeKind } from '~/queries/schema/schema-general'

import { ExperimentMetricForm } from '../ExperimentMetricForm'
import { getDefaultFunnelsMetric, getDefaultTrendsMetric } from '../utils'
import { LegacySharedFunnelsMetricForm } from './LegacySharedFunnelsMetricForm'
import { LegacySharedTrendsMetricForm } from './LegacySharedTrendsMetricForm'
import { sharedMetricLogic } from './sharedMetricLogic'

export const scene: SceneExport = {
    component: SharedMetric,
    logic: sharedMetricLogic,
    paramsToProps: ({ params: { id, action } }) => ({
        sharedMetricId: id === 'new' ? null : parseInt(id),
        action: action || (id === 'new' ? 'create' : 'update'),
    }),
}

export function SharedMetric(): JSX.Element {
    const { sharedMetric, action } = useValues(sharedMetricLogic)
    const { setSharedMetric, createSharedMetric, updateSharedMetric, deleteSharedMetric } =
        useActions(sharedMetricLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { currentTeam } = useValues(teamLogic)

    const { tags: allExistingTags } = useValues(tagsModel)

    if (!sharedMetric || !sharedMetric.query) {
        return (
            <div className="fixed inset-0 flex justify-center items-center">
                <Spinner className="text-5xl" />
            </div>
        )
    }

    return (
        <div className="max-w-[800px]">
            {sharedMetric.query.kind !== NodeKind.ExperimentMetric && (
                <div className="flex gap-4 mb-4">
                    <div
                        className={`flex-1 cursor-pointer p-4 rounded border ${
                            sharedMetric.query.kind === NodeKind.ExperimentTrendsQuery
                                ? 'border-accent bg-accent-highlight-secondary'
                                : 'border-primary'
                        }`}
                        onClick={() => {
                            setSharedMetric({
                                query: getDefaultTrendsMetric(),
                            })
                        }}
                    >
                        <div className="font-semibold flex justify-between items-center">
                            <span>Trend</span>
                            {sharedMetric.query.kind === NodeKind.ExperimentTrendsQuery && (
                                <IconCheckCircle fontSize={18} color="var(--color-accent)" />
                            )}
                        </div>
                        <div className="text-secondary text-sm leading-relaxed">
                            Track a single event, action or a property value.
                        </div>
                    </div>
                    <div
                        className={`flex-1 cursor-pointer p-4 rounded border ${
                            sharedMetric.query.kind === NodeKind.ExperimentFunnelsQuery
                                ? 'border-accent bg-accent-highlight-secondary'
                                : 'border-primary'
                        }`}
                        onClick={() => {
                            setSharedMetric({
                                query: getDefaultFunnelsMetric(),
                            })
                        }}
                    >
                        <div className="font-semibold flex justify-between items-center">
                            <span>Funnel</span>
                            {sharedMetric.query.kind === NodeKind.ExperimentFunnelsQuery && (
                                <IconCheckCircle fontSize={18} color="var(--color-accent)" />
                            )}
                        </div>
                        <div className="text-secondary text-sm leading-relaxed">
                            Analyze conversion rates between sequential steps.
                        </div>
                    </div>
                </div>
            )}
            <div className={`border rounded ${isDarkModeOn ? 'bg-light' : 'bg-white'} p-4`}>
                <div className="mb-4">
                    <LemonLabel className="mb-1">Name</LemonLabel>
                    <LemonInput
                        value={sharedMetric.name}
                        onChange={(newName) => {
                            setSharedMetric({
                                name: newName,
                            })
                        }}
                    />
                </div>
                <div className="mb-4">
                    <LemonLabel className="mb-1">Description (optional)</LemonLabel>
                    <LemonInput
                        value={sharedMetric.description}
                        onChange={(newDescription) => {
                            setSharedMetric({
                                description: newDescription,
                            })
                        }}
                    />
                </div>
                <div className="mb-4">
                    <LemonLabel>Tags</LemonLabel>
                    <div className="mt-2">
                        <ObjectTags
                            tags={sharedMetric.tags || []}
                            onChange={(newTags) => {
                                setSharedMetric({
                                    tags: newTags,
                                })
                            }}
                            saving={false}
                            tagsAvailable={allExistingTags}
                            data-attr="shared-metric-tags"
                        />
                    </div>
                </div>
                {sharedMetric.query.kind === NodeKind.ExperimentMetric ? (
                    <ExperimentMetricForm
                        metric={sharedMetric.query as ExperimentMetric}
                        handleSetMetric={(newMetric) => {
                            setSharedMetric({
                                ...sharedMetric,
                                query: newMetric,
                            })
                        }}
                        filterTestAccounts={currentTeam?.test_account_filters?.length ? true : false}
                    />
                ) : sharedMetric.query.kind === NodeKind.ExperimentTrendsQuery ? (
                    <LegacySharedTrendsMetricForm />
                ) : (
                    <LegacySharedFunnelsMetricForm />
                )}
            </div>
            <div className="flex justify-between mt-4">
                {action === 'update' && (
                    <LemonButton
                        size="medium"
                        type="primary"
                        status="danger"
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Delete this metric?',
                                content: <div className="text-sm text-secondary">This action cannot be undone.</div>,
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    onClick: () => deleteSharedMetric(),
                                    size: 'small',
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                    type: 'tertiary',
                                    size: 'small',
                                },
                            })
                        }}
                    >
                        Delete
                    </LemonButton>
                )}
                <LemonButton
                    className="ml-auto"
                    disabledReason={sharedMetric.name ? undefined : 'You must give your metric a name'}
                    size="medium"
                    type="primary"
                    onClick={() => {
                        if (['create', 'duplicate'].includes(action)) {
                            createSharedMetric()
                            return
                        }

                        updateSharedMetric()
                    }}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
