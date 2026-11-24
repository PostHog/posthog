import { useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { isFilledContainer, toDisplayText } from './jsonText'
import { JsonValue } from './JsonValue'
import { ShowMore } from './ShowMore'

type IOFormat = 'pretty' | 'json'

export interface IOSectionProps {
    title: string
    value: unknown
    highlightQuery?: string | null
}

export function IOSection({ title, value, highlightQuery = null }: IOSectionProps): JSX.Element {
    const [format, setFormat] = useState<IOFormat>('pretty')
    const isContainer = isFilledContainer(value)
    const isEmpty = !isContainer && (value === null || value === undefined || value === '' || typeof value === 'object')

    return (
        <section className="rounded border border-primary bg-surface-primary">
            <header className="flex items-center justify-between gap-2 border-b border-primary px-3 py-1.5">
                <h4 className="m-0 text-xs font-semibold">{title}</h4>
                {isContainer ? (
                    <LemonSegmentedButton
                        size="xsmall"
                        value={format}
                        onChange={setFormat}
                        options={[
                            { value: 'pretty', label: 'Pretty', 'data-attr': 'trace-view-io-pretty' },
                            { value: 'json', label: 'JSON', 'data-attr': 'trace-view-io-json' },
                        ]}
                    />
                ) : null}
            </header>
            <ShowMore highlightQuery={highlightQuery} className="px-3 py-2">
                {isEmpty ? (
                    <span className="text-secondary text-sm">Nothing captured.</span>
                ) : isContainer && format === 'json' ? (
                    <pre className="m-0 whitespace-pre-wrap break-words text-xs">{toDisplayText(value)}</pre>
                ) : (
                    <JsonValue value={value} highlightQuery={highlightQuery} />
                )}
            </ShowMore>
        </section>
    )
}
