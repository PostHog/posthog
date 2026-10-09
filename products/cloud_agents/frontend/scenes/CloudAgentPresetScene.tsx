import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonInputSelect, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { BoxCostLine } from '../components/BoxCostLine'
import { BoxSizeSelect } from '../components/BoxSizeSelect'
import { InferenceModeSelect } from '../components/InferenceModeSelect'
import { LoadErrorBanner } from '../components/LoadErrorBanner'
import { ModelSelect } from '../components/ModelSelect'
import { PresetApiSnippet } from '../components/PresetApiSnippet'
import { RepositoryFields } from '../components/RepositoryFields'
import { RunOptionFields } from '../components/RunOptionFields'
import { CloudAgentPresetLogicProps, cloudAgentPresetLogic } from '../logics/cloudAgentPresetLogic'
import { COST_EXAMPLE_MINUTES } from '../logics/cloudAgentsNewRunLogic'

export const scene: SceneExport<CloudAgentPresetLogicProps> = {
    component: CloudAgentPresetScene,
    logic: cloudAgentPresetLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
    productKey: ProductKey.CLOUD_AGENTS,
}

export function CloudAgentPresetScene({ id }: CloudAgentPresetLogicProps): JSX.Element {
    const enabled = useFeatureFlag('CLOUD_AGENTS')
    const logic = cloudAgentPresetLogic({ id })
    const { isNew, preset, presetLoading, presetLoadError, presetForm, isPresetFormSubmitting } = useValues(logic)
    const { loadPreset, submitPresetForm } = useActions(logic)

    if (!enabled || presetLoadError === 'not_found') {
        return <NotFound object="preset" caption="Check the link, or open the list of presets to find it." />
    }

    const waitingForPreset = !isNew && preset === null

    return (
        <SceneContent>
            <SceneTitleSection
                name={isNew ? 'New preset' : (preset?.name ?? 'Preset')}
                description="A preset is a saved setup for runs. The API can start a run from it with only a prompt."
                resourceType={{ type: 'cloud_agent' }}
                forceBackTo={{ key: 'cloud-agent-presets', name: 'Presets', path: urls.cloudAgentPresets() }}
                actions={
                    <>
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={urls.cloudAgentPresets()}
                            data-attr="cloud-agents-preset-cancel"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            onClick={submitPresetForm}
                            loading={isPresetFormSubmitting}
                            disabledReason={
                                isPresetFormSubmitting
                                    ? 'Saving the preset'
                                    : waitingForPreset
                                      ? 'The preset is not loaded yet'
                                      : undefined
                            }
                            data-attr="cloud-agents-preset-save"
                        >
                            Save preset
                        </LemonButton>
                    </>
                }
            />
            {waitingForPreset && presetLoadError === 'failed' ? (
                <LoadErrorBanner what="this preset" onRetry={loadPreset} retrying={presetLoading} />
            ) : waitingForPreset ? (
                <div className="flex flex-col gap-3">
                    <LemonSkeleton className="h-10" />
                    <LemonSkeleton className="h-48" />
                </div>
            ) : (
                <div className="grid grid-cols-1 items-start gap-4 @min-[56rem]/main-content:grid-cols-3">
                    <Form
                        logic={cloudAgentPresetLogic}
                        props={{ id }}
                        formKey="presetForm"
                        enableFormOnSubmit
                        className="flex min-w-0 flex-col gap-3 @min-[56rem]/main-content:col-span-2"
                    >
                        <LemonField name="name" label="Name" help="API calls use this name to pick the preset.">
                            <LemonInput placeholder="nightly-dependency-updates" data-attr="cloud-agents-preset-name" />
                        </LemonField>
                        <LemonField name="description" label="Description" showOptional>
                            <LemonInput placeholder="What this preset is for" />
                        </LemonField>
                        <RepositoryFields dataAttrPrefix="cloud-agents-preset" />
                        <LemonField name="size" label="Box size">
                            {({ value, onChange }) => (
                                <div className="flex flex-col gap-1">
                                    <BoxSizeSelect
                                        value={value}
                                        onChange={onChange}
                                        emptyLabel="Team default"
                                        data-attr="cloud-agents-preset-size"
                                    />
                                    <BoxCostLine
                                        sizeName={value}
                                        minutes={COST_EXAMPLE_MINUTES}
                                        fallback="Runs use the box size from the team defaults."
                                    />
                                </div>
                            )}
                        </LemonField>
                        <div className="grid grid-cols-1 gap-3 @min-[40rem]/main-content:grid-cols-2">
                            <LemonField name="model" label="Model">
                                {({ value, onChange }) => <ModelSelect value={value} onChange={onChange} />}
                            </LemonField>
                            <LemonField name="inference" label="Model provider">
                                {({ value, onChange }) => (
                                    <InferenceModeSelect value={value} onChange={onChange} emptyLabel="Team default" />
                                )}
                            </LemonField>
                        </div>
                        <LemonField
                            name="instructions"
                            label="Instructions"
                            showOptional
                            help="The agent gets these with each prompt, for example your coding standards or how to run the tests."
                        >
                            <LemonTextArea minRows={4} placeholder="Run pnpm test before you open the pull request." />
                        </LemonField>
                        <RunOptionFields emptyLabel="Team default" dataAttrPrefix="cloud-agents-preset" />
                        <LemonField
                            name="tags"
                            label="Tags"
                            showOptional
                            help="Each run from this preset gets these tags."
                        >
                            <LemonInputSelect mode="multiple" allowCustomValues placeholder="Add a tag" />
                        </LemonField>
                    </Form>
                    <PresetApiSnippet presetName={presetForm.name} />
                </div>
            )}
        </SceneContent>
    )
}
