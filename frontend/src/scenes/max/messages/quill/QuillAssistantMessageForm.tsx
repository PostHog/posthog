import { useActions } from 'kea'

import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { maxThreadLogic } from '../../maxThreadLogic'
import type { AssistantMessageFormProps } from '../AssistantMessageForm'

export function QuillAssistantMessageForm({ form, linksOnly }: AssistantMessageFormProps): JSX.Element {
    const { askMax } = useActions(maxThreadLogic)
    const options = linksOnly ? form.options.filter((option) => option.href) : form.options

    return (
        <div className="flex flex-wrap gap-1.5">
            {options.map((option) => (
                <Button
                    key={option.value}
                    size="sm"
                    variant={option.variant === 'primary' ? 'primary' : 'outline'}
                    onClick={!option.href ? () => askMax(option.value) : undefined}
                    render={option.href ? <LinkPrimitive to={option.href} target="_blank" /> : undefined}
                >
                    {option.value}
                </Button>
            ))}
        </div>
    )
}
