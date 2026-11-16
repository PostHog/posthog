import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'

import { IconArrowLeft, IconPlus } from '@posthog/icons'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { Link } from 'lib/lemon-ui/Link'

import { WebExperimentVariant } from '~/toolbar/shared/experiments/WebExperimentVariant'
import { WebExperimentVariantHeader } from '~/toolbar/shared/experiments/WebExperimentVariantHeader'
import { urls } from '~/toolbar/shared/urls'

import { extensionExperimentsLogic } from '../../logics/panel/extensionExperimentsLogic'
import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'
import { ExtensionExperimentEditorProvider } from './ExtensionExperimentEditorProvider'

const byControlFirst = (a: string, b: string): number =>
    a === 'control' ? -1 : b === 'control' ? 1 : a.localeCompare(b)

export function ExtensionExperimentEditor(): JSX.Element | null {
    const { experimentsState, experimentForm, saving } = useValues(extensionExperimentsLogic)
    const { selectExperiment, sendExperimentsCommand } = useActions(extensionExperimentsLogic)
    const { projectUrl } = useValues(extensionPanelLogic)

    if (!experimentsState || experimentsState.selectedExperimentId === null) {
        return null
    }
    const { selectedExperimentId, selectedVariant, addVariantAvailable, saveResult } = experimentsState
    const isNew = selectedExperimentId === 'new'

    return (
        <ExtensionExperimentEditorProvider>
            <Form
                logic={extensionExperimentsLogic}
                formKey="experimentForm"
                enableFormOnSubmit
                className="flex flex-col gap-2"
            >
                <div className="flex items-center gap-1">
                    <LemonButton
                        size="small"
                        icon={<IconArrowLeft />}
                        tooltip="Back to the experiments"
                        onClick={() => selectExperiment(null)}
                        data-attr="toolbar-extension-experiment-back"
                    />
                    <span className="flex-1 truncate font-semibold">
                        {isNew ? 'New experiment' : experimentForm.name || 'Untitled'}
                    </span>
                    {!isNew && (
                        <Link
                            to={projectUrl(urls.experiment(selectedExperimentId))}
                            target="_blank"
                            className="text-xs"
                        >
                            Open in PostHog <IconOpenInNew />
                        </Link>
                    )}
                </div>
                {saveResult?.status === 'failed' && (
                    <LemonBanner type="error">Couldn't save the experiment: {saveResult.error}</LemonBanner>
                )}
                {isNew && (
                    <Field name="name" label="Experiment name">
                        <LemonInput
                            placeholder="For example: Pricing page conversion"
                            data-attr="toolbar-extension-experiment-name"
                        />
                    </Field>
                )}
                <div className="flex items-center justify-between gap-2">
                    <LemonLabel>Variants</LemonLabel>
                    {addVariantAvailable && (
                        <LemonButton
                            type="secondary"
                            size="xsmall"
                            icon={<IconPlus />}
                            onClick={() => sendExperimentsCommand({ type: 'add-experiment-variant' })}
                            data-attr="toolbar-extension-experiment-add-variant"
                        >
                            Add variant
                        </LemonButton>
                    )}
                </div>
                <div className="text-xs text-secondary">Open a variant to show it on the page.</div>
                <LemonCollapse
                    size="small"
                    activeKey={selectedVariant || null}
                    onChange={(variant) => sendExperimentsCommand({ type: 'select-experiment-variant', variant })}
                    panels={Object.keys(experimentForm.variants)
                        .sort(byControlFirst)
                        .map((variant) => ({
                            key: variant,
                            header: <WebExperimentVariantHeader variant={variant} />,
                            content:
                                variant === 'control' ? (
                                    <div className="text-xs text-secondary">
                                        The control variant is your page in its original state.
                                    </div>
                                ) : (
                                    <WebExperimentVariant key={variant} variant={variant} />
                                ),
                        }))}
                />
                <LemonDivider className="my-1" />
                <div className="flex flex-wrap items-center justify-end gap-2">
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => selectExperiment(null)}
                        data-attr="toolbar-extension-experiment-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="primary"
                        htmlType="submit"
                        loading={saving}
                        data-attr="toolbar-extension-experiment-save"
                    >
                        {isNew ? 'Save as draft' : 'Save experiment'}
                    </LemonButton>
                </div>
            </Form>
        </ExtensionExperimentEditorProvider>
    )
}
