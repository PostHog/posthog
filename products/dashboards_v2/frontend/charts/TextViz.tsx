import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { TextOptions } from './options'
import type { VizProps } from './registry'

export function TextViz({ options }: VizProps<TextOptions>): JSX.Element {
    return (
        <div className="h-full overflow-auto">
            <LemonMarkdown>{options.markdown}</LemonMarkdown>
        </div>
    )
}
