import { useActions, useValues } from 'kea'

import {
    DropdownMenu,
    DropdownMenuContent,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
} from '@posthog/quill'

import { AnnotationScope } from '~/types'

import { annotationScopesMenuOptions, annotationsLogic } from '../logics/annotationsLogic'

// The filter menu takes string values, so "Any" scope (null in the logic) gets a stand-in.
const ANY_SCOPE = 'any'

type ScopeValue = AnnotationScope | typeof ANY_SCOPE

const SCOPE_OPTIONS: FilterOption<ScopeValue>[] = annotationScopesMenuOptions().flatMap((option) =>
    'value' in option ? [{ value: option.value ?? ANY_SCOPE, label: String(option.label) }] : []
)

/** The annotations list's scope filter, in the quill filter menu. */
export function QuillAnnotationsFilterMenu(): JSX.Element {
    const { scope } = useValues(annotationsLogic)
    const { setScope } = useActions(annotationsLogic)

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={scope !== null} dataAttr="annotations-filter" />
            <DropdownMenuContent align="end" className="min-w-56">
                <FilterRadioSubMenu<ScopeValue>
                    label="Scope"
                    options={SCOPE_OPTIONS}
                    value={scope ?? ANY_SCOPE}
                    defaultValue={ANY_SCOPE}
                    onChange={(next) => setScope(next === ANY_SCOPE ? null : next)}
                />
                <FilterClearItem active={scope !== null} onClear={() => setScope(null)} />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
