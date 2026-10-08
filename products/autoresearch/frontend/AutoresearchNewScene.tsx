import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { autoresearchNewLogic } from './autoresearchNewLogic'
import { AdvancedSettings } from './newModel/AdvancedSettings'
import { DefinitionSentence } from './newModel/DefinitionSentence'
import { ReadinessChecklist } from './newModel/ReadinessChecklist'
import { TemplateChips } from './newModel/TemplateChips'
import { WhatHappensNext } from './newModel/WhatHappensNext'

export const scene: SceneExport = {
    component: AutoresearchNewScene,
    logic: autoresearchNewLogic,
}

export function AutoresearchNewScene(): JSX.Element {
    const isEnabled = useFeatureFlag('AUTORESEARCH')
    const { isNewPipelineSubmitting, submitIntent, startTrainingDisabledReason, saveDraftDisabledReason } =
        useValues(autoresearchNewLogic)
    const { submitWithIntent } = useActions(autoresearchNewLogic)

    if (!isEnabled) {
        return <NotFound object="Autoresearch" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <div className="mb-2">
                <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} to={urls.autoresearch()}>
                    Back to models
                </LemonButton>
            </div>
            <SceneTitleSection
                name="New model"
                description="Pick a template or describe who to predict, what they will do, and when. Autoresearch trains models to predict it."
                resourceType={{ type: 'experiment' }}
            />

            <div className="grid grid-cols-1 @min-[48rem]/main-content:grid-cols-[1fr_360px] gap-6 items-start">
                <Form
                    logic={autoresearchNewLogic}
                    formKey="newPipeline"
                    className="flex flex-col gap-4 border rounded p-4"
                >
                    <TemplateChips />

                    <DefinitionSentence />

                    <LemonField name="name" label="Name">
                        <LemonInput placeholder="e.g. File sharing prediction" />
                    </LemonField>

                    <AdvancedSettings />

                    <div className="flex justify-end gap-2 mt-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => router.actions.push(urls.autoresearch())}
                            data-attr="autoresearch-new-cancel"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            loading={isNewPipelineSubmitting && submitIntent === 'draft'}
                            disabledReason={saveDraftDisabledReason}
                            onClick={() => submitWithIntent('draft')}
                            data-attr="autoresearch-new-save-draft"
                        >
                            Save as draft
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            loading={isNewPipelineSubmitting && submitIntent === 'train'}
                            disabledReason={startTrainingDisabledReason}
                            onClick={() => submitWithIntent('train')}
                            data-attr="autoresearch-new-start-training"
                        >
                            Start training
                        </LemonButton>
                    </div>
                </Form>

                <div className="flex flex-col gap-4">
                    <ReadinessChecklist />
                    <WhatHappensNext />
                </div>
            </div>
        </SceneContent>
    )
}
