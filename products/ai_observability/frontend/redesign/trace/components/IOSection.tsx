import { useMemo, useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { getJsonContainerForDisplay } from '../../../components/JSONValueDisplay'
import { isPlainObject, toDisplayText } from './jsonText'
import { JsonTree } from './JsonTree'
import { KeyValueTable } from './KeyValueTable'
import { ShowMore } from './ShowMore'

type IOFormat = 'pretty' | 'json'

export interface IOSectionProps {
    title: string
    value: unknown
    highlightQuery?: string | null
}

export function IOSection({ title, value: capturedValue, highlightQuery = null }: IOSectionProps): JSX.Element {
    const [format, setFormat] = useState<IOFormat>('pretty')
    const value = useMemo(
        () => getJsonContainerForDisplay(capturedValue, { allowEmptyContainers: false }) ?? capturedValue,
        [capturedValue]
    )
    const isEmpty =
        value === null ||
        value === undefined ||
        value === '' ||
        (isPlainObject(value) && Object.keys(value).length === 0)

    return (
        <section className="rounded border border-primary bg-surface-primary">
            <header className="flex items-center justify-between gap-2 border-b border-primary px-3 py-1.5">
                <h4 className="m-0 text-xs font-semibold">{title}</h4>
                {isPlainObject(value) || Array.isArray(value) ? (
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
                ) : isPlainObject(value) && format === 'pretty' ? (
                    <KeyValueTable entries={Object.entries(value)} highlightQuery={highlightQuery} />
                ) : Array.isArray(value) && format === 'pretty' ? (
                    <JsonTree src={value} highlightQuery={highlightQuery} />
                ) : typeof value === 'string' ? (
                    <p className="m-0 whitespace-pre-wrap break-words text-sm">{value}</p>
                ) : (
                    <pre className="m-0 whitespace-pre-wrap break-words text-xs">{toDisplayText(value)}</pre>
                )}
            </ShowMore>
        </section>
    )
}
