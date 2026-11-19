import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import PropertyFiltersDisplay from 'lib/components/PropertyFilters/components/PropertyFiltersDisplay'

import { AnyPropertyFilter } from '~/types'

import type { TaggerApi } from '../generated/api.schemas'
import { providerLabel } from '../settings/providerKeyStateUtils'

function ConfigField({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="space-y-1">
            <div className="font-semibold">{label}</div>
            {children}
        </div>
    )
}

export function TaggerConfiguration({ tagger }: { tagger: TaggerApi }): JSX.Element {
    const config = tagger.tagger_config
    const isHog = tagger.tagger_type === 'hog'
    const tags = config.tags ?? []
    const conditions = tagger.conditions ?? []

    return (
        <div className="space-y-6 max-w-3xl">
            {tagger.description && <ConfigField label="Description">{tagger.description}</ConfigField>}

            <ConfigField label="Method">{isHog ? 'Hog code' : 'LLM'}</ConfigField>

            {'source' in config ? (
                <ConfigField label="Hog code">
                    <CodeSnippet language={Language.Text} thing="Hog code">
                        {config.source}
                    </CodeSnippet>
                </ConfigField>
            ) : (
                <ConfigField label="Prompt">
                    <CodeSnippet language={Language.Text} wrap thing="prompt">
                        {config.prompt}
                    </CodeSnippet>
                </ConfigField>
            )}

            <ConfigField label="Tags">
                {tags.length > 0 ? (
                    <div className="flex flex-wrap gap-1">
                        {tags.map((tag) => (
                            <Tooltip key={tag.name} title={tag.description || undefined}>
                                <LemonTag type="highlight">{tag.name}</LemonTag>
                            </Tooltip>
                        ))}
                    </div>
                ) : (
                    <span className="text-muted">Any tag the Hog code returns</span>
                )}
            </ConfigField>

            {'prompt' in config && (
                <ConfigField label="Tags per generation">
                    {config.min_tags ?? 0} to {config.max_tags ?? 'any number'}
                </ConfigField>
            )}

            {!isHog && tagger.model_configuration && (
                <ConfigField label="Model">
                    {providerLabel(tagger.model_configuration.provider)} {tagger.model_configuration.model}
                    {tagger.model_configuration.provider_key_name && (
                        <span className="text-muted"> (key: {tagger.model_configuration.provider_key_name})</span>
                    )}
                </ConfigField>
            )}

            <ConfigField label="Conditions">
                <div className="space-y-2">
                    {conditions.map((condition, index) => (
                        <div key={condition.id} className="border rounded p-3 space-y-2">
                            <div className="text-sm">
                                {index > 0 && <span className="text-muted">OR </span>}
                                {condition.rollout_percentage ?? 100}% of generations
                                {condition.properties?.length ? ' matching:' : ''}
                            </div>
                            {condition.properties?.length ? (
                                <PropertyFiltersDisplay filters={condition.properties as AnyPropertyFilter[]} compact />
                            ) : null}
                        </div>
                    ))}
                </div>
            </ConfigField>
        </div>
    )
}
