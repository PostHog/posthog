import { LemonLabel } from '@posthog/lemon-ui'

import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { useWebExperimentEditor } from '~/toolbar/shared/experiments/webExperimentEditorContext'
import type { WebExperimentUrlMatchType } from '~/toolbar/shared/types'

const URL_MATCH_OPTIONS: { value: WebExperimentUrlMatchType; label: string }[] = [
    { value: 'icontains', label: 'contains' },
    { value: 'not_icontains', label: 'does not contain' },
    { value: 'exact', label: 'is' },
    { value: 'is_not', label: 'is not' },
    { value: 'regex', label: 'matches regex' },
    { value: 'not_regex', label: 'does not match regex' },
]

interface WebExperimentVariantUrlConditionProps {
    variant: string
}

export function WebExperimentVariantUrlCondition({ variant }: WebExperimentVariantUrlConditionProps): JSX.Element {
    const { variants, setVariantUrlCondition } = useWebExperimentEditor()
    const conditions = variants[variant]?.conditions
    const url = conditions?.url ?? ''
    const urlMatchType = conditions?.urlMatchType ?? 'icontains'

    return (
        <div>
            <LemonLabel>Pages to change</LemonLabel>
            <div className="flex flex-wrap items-center gap-2 my-1">
                <span>URL</span>
                <LemonSelect
                    size="small"
                    value={urlMatchType}
                    options={URL_MATCH_OPTIONS}
                    onChange={(newUrlMatchType) => setVariantUrlCondition(variant, url, newUrlMatchType)}
                    data-attr="web-experiment-variant-url-match-type"
                />
                <LemonInput
                    size="small"
                    className="flex-1 min-w-40"
                    value={url}
                    onChange={(newUrl) => setVariantUrlCondition(variant, newUrl, urlMatchType)}
                    placeholder="https://example.com/pricing"
                    data-attr="web-experiment-variant-url"
                />
            </div>
            <span className="text-xs text-secondary">Leave empty to change every page the element is on.</span>
        </div>
    )
}
