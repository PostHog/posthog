import { IconArrowRight } from '@posthog/icons'
import { Field, Input, Text } from '@posthog/quill'

import { PathCleanFilterAddItemButton } from 'lib/components/PathCleanFilters/PathCleanFilterAddItemButton'
import { PathCleanFiltersTable } from 'lib/components/PathCleanFilters/PathCleanFiltersTable'
import { PathCleaningRulesDebugger } from 'lib/components/PathCleanFilters/PathCleaningRulesDebugger'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'
import { PathCleaningSuggestionsBanner } from 'scenes/settings/environment/PathCleaningSuggestionsBanner'

import { PathCleaningFilter } from '~/types'

export function QuillPathCleaningFiltersConfig({
    filters,
    testValue,
    onTestValueChange,
    readableTestPath,
    restrictedReason,
    onFiltersChange,
    onAddFilter,
}: {
    filters: PathCleaningFilter[]
    testValue: string
    onTestValueChange: (value: string) => void
    readableTestPath: JSX.Element[]
    restrictedReason: string | null
    onFiltersChange: (filters: PathCleaningFilter[]) => void
    onAddFilter: (filter: PathCleaningFilter) => void
}): JSX.Element {
    return (
        <QuillSurfaceContext.Provider value={true}>
            <div className="flex flex-col gap-4">
                <PathCleaningSuggestionsBanner />
                <div className="flex flex-col gap-2">
                    <PathCleanFiltersTable filters={filters} setFilters={onFiltersChange} />
                    <div>
                        <PathCleanFilterAddItemButton onAdd={onAddFilter} />
                    </div>
                </div>
                <div className="flex flex-col gap-2">
                    <Text size="xs" render={<p className="m-0" />}>
                        Wanna test what your cleaned path will look like? Try them out here.
                    </Text>
                    <div className="flex flex-wrap items-center gap-2">
                        <Field className="min-w-60 flex-1">
                            <Input
                                aria-label="Path to test"
                                value={testValue}
                                onChange={(event) => onTestValueChange(event.target.value)}
                                placeholder="Enter a path to test"
                                disabledReason={restrictedReason}
                            />
                        </Field>
                        <IconArrowRight className="shrink-0 text-muted-foreground" />
                        <span
                            className="inline-flex min-h-8 min-w-60 flex-1 items-center rounded-md border border-border px-2 font-mono text-xs"
                            translate="no"
                        >
                            {readableTestPath}
                        </span>
                    </div>
                </div>
                <PathCleaningRulesDebugger testPath={testValue} filters={filters} finalResult={readableTestPath} />
            </div>
        </QuillSurfaceContext.Provider>
    )
}
