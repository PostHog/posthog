import { useActions, useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Toggle } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { stringifiedExamples } from '~/queries/examples'

import { debugSceneLogic } from './debugSceneLogic'

export function QuillDebugSceneActions(): JSX.Element {
    const { query1, query2 } = useValues(debugSceneLogic)
    const { setQuery1, setQuery2 } = useActions(debugSceneLogic)
    const hogEnabled = useFeatureFlag('HOG')

    const presets: { label: string; query: string }[] = [
        { label: 'SQL Debug', query: stringifiedExamples.HogQLRaw },
        ...(hogEnabled ? [{ label: 'Hog', query: stringifiedExamples.Hoggonacci }] : []),
        { label: 'SQL Table', query: stringifiedExamples.HogQLTable },
        { label: 'Any Query', query: stringifiedExamples.Events },
    ]
    const moreSamples = Object.entries(stringifiedExamples).filter(([k]) => k !== 'HogQLTable' && k !== 'HogQLRaw')

    return (
        <div className="flex flex-wrap items-center gap-1">
            <Toggle pressed={!!query2} onPressedChange={() => (query2 ? setQuery2('') : setQuery2(query1))}>
                Split
            </Toggle>
            {presets.map(({ label, query }) => (
                <Toggle key={label} pressed={query1 === query} onPressedChange={() => setQuery1(query)}>
                    {label}
                </Toggle>
            ))}
            <Select<string>
                value={null}
                onValueChange={(v) => {
                    if (v) {
                        setQuery1(v)
                    }
                }}
            >
                <SelectTrigger>
                    <SelectValue placeholder="More sample queries" />
                </SelectTrigger>
                <SelectContent>
                    {moreSamples.map(([k, v]) => (
                        <SelectItem key={k} value={v}>
                            {k}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}
