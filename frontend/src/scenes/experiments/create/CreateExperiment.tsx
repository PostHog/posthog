import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useState } from 'react'

import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { MetricsReorderModal } from '../MetricsView/MetricsReorderModal'
import { ExperimentTypePanel } from './ExperimentTypePanel'
import { VariantsPanel } from './VariantsPanel'
import { createExperimentLogic } from './createExperimentLogic'

const LemonFieldError = ({ error }: { error: string }): JSX.Element => {
    return (
        <div className="text-danger flex items-center gap-1 text-sm">
            <IconErrorOutline className="text-xl shrink-0" /> {error}
        </div>
    )
}

export const CreateExperiment = (): JSX.Element => {
    const { HogfettiComponent } = useHogfetti({ count: 100, duration: 3000 })

    const { experiment, experimentErrors } = useValues(createExperimentLogic)
    const { setExperiment, setExperimentValue } = useActions(createExperimentLogic)

    const [selectedPanel, setSelectedPanel] = useState<string | null>(null)

    return (
        <div className="flex flex-col xl:grid xl:grid-cols-[1fr_400px] gap-x-4 h-full">
            <Form logic={createExperimentLogic} formKey="experiment" enableFormOnSubmit>
                <HogfettiComponent />
                <SceneContent className="max-w-none flex-1">
                    <SceneTitleSection
                        name={experiment.name}
                        description={null}
                        resourceType={{
                            type: 'experiment',
                        }}
                        canEdit
                        forceEdit
                        onNameChange={(name) => {
                            setExperimentValue('name', name)
                        }}
                        actions={
                            <>
                                <LemonButton
                                    data-attr="cancel-experiment"
                                    type="secondary"
                                    size="small"
                                    onClick={() => {
                                        router.actions.push(urls.experiments())
                                    }}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton data-attr="save-experiment" type="primary" size="small" htmlType="submit">
                                    Save as draft
                                </LemonButton>
                            </>
                        }
                    />
                    {experimentErrors.name && typeof experimentErrors.name === 'string' && (
                        <LemonFieldError error={experimentErrors.name} />
                    )}
                    <SceneDivider />
                    <SceneSection title="Hypothesis" description="Describe your experiment in a few sentences.">
                        <LemonField name="description">
                            <LemonTextArea
                                placeholder="The goal of this experiment is ..."
                                data-attr="experiment-hypothesis"
                                value={experiment.description}
                                onChange={(value) => {
                                    setExperimentValue('description', value)
                                }}
                            />
                        </LemonField>
                    </SceneSection>
                    <SceneDivider />
                    <LemonCollapse
                        activeKey={selectedPanel ?? undefined}
                        onChange={(key) => {
                            setSelectedPanel(key as string | null)
                        }}
                        className="bg-surface-primary"
                        panels={[
                            {
                                key: 'experiment-type',
                                header: 'Experiment type',
                                content: (
                                    <ExperimentTypePanel
                                        experiment={experiment}
                                        setExperimentType={(type) => setExperiment({ ...experiment, type })}
                                    />
                                ),
                            },
                            {
                                key: 'experiment-variants',
                                header: 'Feature flag & variants',
                                content: (
                                    <div className="p-4">
                                        <VariantsPanel experiment={experiment} onChange={(updates) => updates} />
                                    </div>
                                ),
                            },
                            {
                                key: 'experiment-targeting',
                                header: 'Targeting',
                                content: (
                                    <div className="p-4">
                                        <span>Targeting Panel Goes Here</span>
                                    </div>
                                ),
                            },
                            {
                                key: 'experiment-exposure',
                                header: 'Exposure criteria',
                                content: (
                                    <div className="p-4">
                                        <span>Exposure Criteria Panel Goes Here</span>
                                    </div>
                                ),
                            },
                            {
                                key: 'experiment-metrics',
                                header: 'Metrics',
                                content: (
                                    <div className="p-4">
                                        <span>Metrics Panel Goes Here</span>
                                    </div>
                                ),
                            },
                        ]}
                    />
                </SceneContent>
            </Form>
            {/* Sidebar Checklist */}
            <div className="h-full">
                <div className="sticky top-16">
                    <span>Sidebar Checklist Goes Here</span>
                </div>
            </div>

            {/* Metric Modals */}
            <MetricSourceModal isSecondary={false} />
            <MetricSourceModal isSecondary={true} />
            <MetricsReorderModal isSecondary={false} />
            <MetricsReorderModal isSecondary={true} />
        </div>
    )
}
