import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SelectableCard } from '../components/SelectableCard'
import { createExperimentLogic } from './createExperimentLogic'

export const CreateExperiment = () => {
    const { experiment, experimentErrors, experimentHasErrors } = useValues(createExperimentLogic)
    const { setExperimentValue, submitExperiment } = useActions(createExperimentLogic)

    const [selectedPanel, setSelectedPanel] = useState<'experiment-type' | null>(null)

    return (
        <Form logic={createExperimentLogic} formKey="experiment" enableFormOnSubmit>
            <SceneContent className="max-w-2/3">
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
                    onDescriptionChange={(description) => {
                        setExperimentValue('description', description)
                    }}
                    actions={
                        <>
                            <LemonButton
                                data-attr="cancel-experiment"
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    console.log('cancel experiment')
                                }}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                data-attr="save-experiment"
                                type="primary"
                                size="small"
                                onClick={() => {
                                    submitExperiment()
                                }}
                            >
                                Save
                            </LemonButton>
                        </>
                    }
                />
                {experimentErrors?.name && <LemonBanner type="error">{experimentErrors.name}</LemonBanner>}
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
                        setSelectedPanel(key as 'experiment-type')
                    }}
                    className="bg-surface-primary"
                    panels={[
                        {
                            key: 'experiment-type',
                            header: 'Experiment type',
                            content: (
                                <div className="flex gap-4 mb-4">
                                    <SelectableCard
                                        title="Product experiment"
                                        description="Use custom code to manage how variants modify your product."
                                        selected={experiment.type === 'product'}
                                        onClick={() => setExperimentValue('type', 'product')}
                                    />
                                    <SelectableCard
                                        title={
                                            <span>
                                                No-Code experiment{' '}
                                                <LemonTag type="option" size="small">
                                                    Beta
                                                </LemonTag>
                                            </span>
                                        }
                                        description="Define variants on your website using the PostHog toolbar, no coding required."
                                        selected={experiment.type === 'web'}
                                        onClick={() => setExperimentValue('type', 'web')}
                                    />
                                </div>
                            ),
                        },
                        {
                            key: 'experiment-targeting',
                            header: 'Targeting',
                            content: <div>Targeting</div>,
                        },
                        {
                            key: 'experiment-variants',
                            header: 'Variants',
                            content: <div>Variants</div>,
                        },
                        {
                            key: 'experiment-metrics',
                            header: 'Metrics',
                            content: <div>Targeting</div>,
                        },
                    ]}
                />
            </SceneContent>
        </Form>
    )
}
