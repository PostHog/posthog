import { useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { toDisplayText } from './jsonText'
import { KeyValueTable } from './KeyValueTable'

type IOFormat = 'pretty' | 'json'

export interface IOSectionProps {
    title: string
    value: unknown
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function IOSection({ title, value }: IOSectionProps): JSX.Element {
    const [format, setFormat] = useState<IOFormat>('pretty')
    const isEmpty =
        value === null ||
        value === undefined ||
        value === '' ||
        (isPlainObject(value) && Object.keys(value).length === 0)

    return (
        <section className="rounded border border-primary bg-surface-primary">
            <header className="flex items-center justify-between gap-2 border-b border-primary px-3 py-1.5">
                <h4 className="m-0 text-xs font-semibold">{title}</h4>
                {isPlainObject(value) ? (
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
            <div className="px-3 py-2">
                {isEmpty ? (
                    <span className="text-secondary text-sm">Nothing captured.</span>
                ) : isPlainObject(value) && format === 'pretty' ? (
                    <KeyValueTable entries={Object.entries(value)} />
                ) : typeof value === 'string' ? (
                    <p className="m-0 whitespace-pre-wrap break-words text-sm">{value}</p>
                ) : (
                    <pre className="m-0 overflow-auto text-xs">{toDisplayText(value)}</pre>
                )}
            </div>
        </section>
    )
}
