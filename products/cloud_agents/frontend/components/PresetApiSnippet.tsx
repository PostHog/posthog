import { LemonCard } from '@posthog/lemon-ui'

import { CurlSnippet } from './CurlSnippet'

/** How to start a run from this preset over the API: the preset name and a prompt are the whole request. */
export function PresetApiSnippet({ presetName }: { presetName: string }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-4 min-w-0">
            <h3 className="m-0 text-base font-semibold">Trigger this preset from the API</h3>
            <p className="m-0 text-secondary text-xs">
                The preset supplies the repository, the box size and the instructions. The request needs only the preset
                name and a prompt.
            </p>
            <CurlSnippet
                surface="preset"
                body={{ preset: presetName.trim() || '<name>', prompt: 'Fix the failing checkout test' }}
            />
        </LemonCard>
    )
}
