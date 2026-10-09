import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { COST_EXAMPLE_MINUTES, cloudAgentsNewRunLogic } from '../logics/cloudAgentsNewRunLogic'
import { BoxCostLine } from './BoxCostLine'
import { BoxSizeSelect } from './BoxSizeSelect'
import { InferenceModeSelect } from './InferenceModeSelect'
import { RepositoryFields } from './RepositoryFields'
import { RunOptionFields } from './RunOptionFields'

/** The form that starts a run. A preset fills the fields, and each field can still change for this one run. */
export function NewRunModal(): JSX.Element {
    const { isNewRunModalOpen, isNewRunSubmitting, newRun, newRunError, presets } = useValues(cloudAgentsNewRunLogic)
    const { closeNewRunModal, selectPreset, submitNewRun } = useActions(cloudAgentsNewRunLogic)

    return (
        <LemonModal
            isOpen={isNewRunModalOpen}
            onClose={closeNewRunModal}
            title="New run"
            description="The agent works on your prompt in a cloud sandbox and opens a pull request when it is done."
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeNewRunModal} data-attr="cloud-agents-new-run-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitNewRun}
                        loading={isNewRunSubmitting}
                        disabledReason={isNewRunSubmitting ? 'Starting the run' : undefined}
                        data-attr="cloud-agents-new-run-submit"
                    >
                        Start run
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={cloudAgentsNewRunLogic}
                formKey="newRun"
                enableFormOnSubmit
                className="@container flex flex-col gap-3"
            >
                {newRunError && <LemonBanner type="error">{newRunError}</LemonBanner>}
                <LemonField name="prompt" label="Prompt">
                    <LemonTextArea
                        placeholder="Describe the change, for example: Add a dark mode toggle to the settings page"
                        minRows={4}
                        data-attr="cloud-agents-new-run-prompt"
                    />
                </LemonField>
                <LemonField
                    name="preset"
                    label="Preset"
                    showOptional
                    help="A preset fills in the fields below. You can still change them for this run."
                >
                    <LemonSelect
                        fullWidth
                        value={newRun.preset}
                        onChange={(preset) => selectPreset(preset)}
                        options={[
                            { value: null, label: 'No preset' },
                            ...(presets ?? []).map((preset) => ({ value: preset.name, label: preset.name })),
                        ]}
                        data-attr="cloud-agents-new-run-preset"
                    />
                </LemonField>
                <RepositoryFields required dataAttrPrefix="cloud-agents-new-run" />
                <LemonField name="size" label="Box size">
                    {({ value, onChange }) => (
                        <div className="flex flex-col gap-1">
                            <BoxSizeSelect
                                value={value}
                                onChange={onChange}
                                emptyLabel="Default size"
                                data-attr="cloud-agents-new-run-size"
                            />
                            <BoxCostLine
                                sizeName={value}
                                minutes={COST_EXAMPLE_MINUTES}
                                fallback="Choose a box size to see its price."
                            />
                        </div>
                    )}
                </LemonField>
                <LemonField name="inference" label="Model provider">
                    {({ value, onChange }) => (
                        <InferenceModeSelect
                            value={value}
                            onChange={onChange}
                            emptyLabel="Default"
                            data-attr="cloud-agents-new-run-inference"
                        />
                    )}
                </LemonField>
                <RunOptionFields emptyLabel="Default" dataAttrPrefix="cloud-agents-new-run" />
            </Form>
        </LemonModal>
    )
}
