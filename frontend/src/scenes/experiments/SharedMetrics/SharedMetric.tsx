import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonLabel, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { NodeKind } from '~/queries/schema/schema-general'

import { getDefaultFunnelsMetric, getDefaultTrendsMetric } from '../experimentLogic'
import { SharedFunnelsMetricForm } from './SharedFunnelsMetricForm'
import { sharedMetricLogic } from './sharedMetricLogic'
import { SharedTrendsMetricForm } from './SharedTrendsMetricForm'
export const scene: SceneExport = {
    component: SharedMetric,
    logic: sharedMetricLogic,
    paramsToProps: ({ params: { id } }) => ({
        sharedMetricId: id === 'new' ? 'new' : parseInt(id),
    }),
}

export function SharedMetric(): JSX.Element {
    const { sharedMetricId, sharedMetric } = useValues(sharedMetricLogic)
    const { setSharedMetric, createSharedMetric, updateSharedMetric, deleteSharedMetric } =
        useActions(sharedMetricLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    if (!sharedMetric || !sharedMetric.query) {
        return (
            <div className="fixed inset-0 flex justify-center items-center">
                <Spinner className="text-5xl" />
            </div>
        )
    }

    return (
        <div className="max-w-[800px]">
            <div className="flex gap-4 mb-4">
                <div
                    className={`flex-1 cursor-pointer p-4 rounded border ${
                        sharedMetric.query.kind === NodeKind.ExperimentTrendsQuery
                            ? 'border-primary bg-primary-highlight'
                            : 'border-border'
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
                            <IconCheckCircle fontSize={18} color="var(--primary)" />
                        )}
                    </div>
                    <div className="text-muted text-sm leading-relaxed">
                        Track a single event, action or a property value.
                    </div>
                </div>
                <div
                    className={`flex-1 cursor-pointer p-4 rounded border ${
                        sharedMetric.query.kind === NodeKind.ExperimentFunnelsQuery
                            ? 'border-primary bg-primary-highlight'
                            : 'border-border'
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
                            <IconCheckCircle fontSize={18} color="var(--primary)" />
                        )}
                    </div>
                    <div className="text-muted text-sm leading-relaxed">
                        Analyze conversion rates between sequential steps.
                    </div>
                </div>
            </div>
            <div className={`border rounded ${isDarkModeOn ? 'bg-light' : 'bg-white'} p-4`}>
                <div className="mb-4">
                    <LemonLabel>Name</LemonLabel>
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
                    <LemonLabel>Description (optional)</LemonLabel>
                    <LemonInput
                        value={sharedMetric.description}
                        onChange={(newDescription) => {
                            setSharedMetric({
                                description: newDescription,
                            })
                        }}
                    />
                </div>
                {sharedMetric.query.kind === NodeKind.ExperimentTrendsQuery ? (
                    <SharedTrendsMetricForm />
                ) : (
                    <SharedFunnelsMetricForm />
                )}
            </div>
            <div className="flex justify-between mt-4">
                <LemonButton
                    size="medium"
                    type="primary"
                    status="danger"
                    onClick={() => {
                        LemonDialog.open({
                            title: 'Delete this metric?',
                            content: <div className="text-sm text-muted">This action cannot be undone.</div>,
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
                <LemonButton
                    disabledReason={sharedMetric.name ? undefined : 'You must give your metric a name'}
                    size="medium"
                    type="primary"
                    onClick={() => {
                        if (sharedMetricId === 'new') {
                            createSharedMetric()
                        } else {
                            updateSharedMetric()
                        }
                    }}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
