import { IconPencil, IconSearch, IconTrash } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { StepField } from '~/toolbar/shared/actions/StepField'
import { SelectorQualityWarning } from '~/toolbar/shared/elements/SelectorQualityWarning'
import { ActionStepForm } from '~/toolbar/shared/types'

interface ActionStepEditorProps {
    step: ActionStepForm
    index: number
    /** True while the user picks this step's element on the page. */
    inspecting: boolean
    onInspect: () => void
    onEditSelector: () => void
    onRemove: () => void
}

/** One element of an action form. Render it inside the form's `Group name={['steps', index]}`. */
export function ActionStepEditor({
    step,
    index,
    inspecting,
    onInspect,
    onEditSelector,
    onRemove,
}: ActionStepEditorProps): JSX.Element {
    return (
        <>
            <div className="flex flex-row justify-between">
                <h3>
                    {index > 0 ? 'OR ' : null}Element #{index + 1}
                </h3>
                <LemonButton type="tertiary" size="small" onClick={onRemove} sideIcon={<IconTrash />}>
                    Remove
                </LemonButton>
            </div>

            <div className="action-inspect">
                <LemonButton
                    size="small"
                    type={inspecting ? 'primary' : 'secondary'}
                    onClick={(e) => {
                        e.stopPropagation()
                        onInspect()
                    }}
                    icon={<IconSearch />}
                >
                    {step?.event === '$autocapture' ? 'Change Element' : 'Select Element'}
                </LemonButton>
            </div>

            {step?.event === '$autocapture' || inspecting ? (
                <>
                    <StepField
                        step={step}
                        item="selector"
                        label="Selector"
                        caption="CSS selector that uniquely identifies your element"
                    />
                    <SelectorQualityWarning selector={step?.selector} />
                    <div className="flex flex-row justify-end mb-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconPencil />}
                            onClick={(e) => {
                                e.stopPropagation()
                                onEditSelector()
                            }}
                        >
                            Edit the selector
                        </LemonButton>
                    </div>
                    <StepField
                        step={step}
                        item="href"
                        label="Link target"
                        caption={
                            <>
                                If your element is a link, the location that the link opens (<code>href</code> tag)
                            </>
                        }
                    />
                    <LemonTag type="highlight">
                        <span className="uppercase">and</span>
                    </LemonTag>
                    <StepField step={step} item="text" label="Text" caption="Text content inside your element" />
                    <LemonTag type="highlight">
                        <span className="uppercase">and</span>
                    </LemonTag>
                    <StepField
                        step={step}
                        item="url"
                        label="Page URL"
                        caption="Elements will match only when triggered from the URL."
                    />
                </>
            ) : null}
        </>
    )
}
