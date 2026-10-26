import { useActions } from 'kea'

import { LemonButton, LemonButtonPropsBase } from '@posthog/lemon-ui'

import { AssistantForm } from '~/queries/schema/schema-assistant-messages'

import { useQuillThread } from 'products/posthog_ai/frontend/api/primitives'

import { maxThreadLogic } from '../maxThreadLogic'
import { QuillAssistantMessageForm } from './quill/QuillAssistantMessageForm'

export interface AssistantMessageFormProps {
    form: AssistantForm
    linksOnly?: boolean
}

export function AssistantMessageForm(props: AssistantMessageFormProps): JSX.Element {
    return useQuillThread() ? <QuillAssistantMessageForm {...props} /> : <LemonAssistantMessageForm {...props} />
}

function LemonAssistantMessageForm({ form, linksOnly }: AssistantMessageFormProps): JSX.Element {
    const { askMax } = useActions(maxThreadLogic)
    const options = linksOnly ? form.options.filter((option) => option.href) : form.options

    return (
        // ml-1 is because buttons have radius of 0.375rem, while messages of 0.65rem, where diff = 0.25rem
        // Also makes it clear the form is subservient to the message. *Harmony*
        <div className="flex flex-wrap gap-1.5 ml-1 mt-1">
            {options.map((option) => (
                <LemonButton
                    key={option.value}
                    onClick={!option.href ? () => askMax(option.value) : undefined}
                    to={option.href}
                    size="small"
                    targetBlank={!!option.href}
                    type={
                        option.variant && ['primary', 'secondary', 'tertiary'].includes(option.variant)
                            ? (option.variant as LemonButtonPropsBase['type'])
                            : 'secondary'
                    }
                >
                    {option.value}
                </LemonButton>
            ))}
        </div>
    )
}
