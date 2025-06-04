import { useValues } from 'kea'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'

import { STL as hogvmSTL } from '@posthog/hogvm'
import { LemonButton, LemonButtonWithDropdown, LemonMenu } from '@posthog/lemon-ui'
import { IconMagic } from '@posthog/icons'

export type HogFunctionTemplateSuggestionsProps = {
    templating: 'hog' | 'liquid'
    value: string
}

export function HogFunctionTemplateSuggestions({ templating, value }: HogFunctionTemplateSuggestionsProps): JSX.Element {
    const { logicProps } = useValues(hogFunctionConfigurationLogic)


    return (
        <div className="p-3 rounded border deprecated-space-y-2 bg-surface-primary">
            <LemonLabel>Suggestions</LemonLabel>
            <CodeSnippet thing="Suggestions">
                {templating === 'hog' ? hogvmSTL : ''}
            </CodeSnippet>

            <p className="text-sm">
                Use this URL in your external system to send events to PostHog. The webhook can be called with a POST
                request and any JSON payload. You can then use the configuration options to parse the{' '}
                <code>request.body</code> or <code>request.headers</code> to map to the required fields.
            </p>
        </div>
    )
}


export function HogFunctionTemplateSuggestionsButton(): JSX.Element {
    return (
        <LemonMenu>
            <LemonButton icon={<IconMagic/>}>
            </LemonButton>
        </LemonMenu>
    )
