import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import type { TaggerApi } from '../generated/api.schemas'
import { providerLabel } from '../settings/providerKeyStateUtils'
import { TaggerConditionRow } from './TaggerConditionRow'
import { TaggerConfigField } from './TaggerConfigField'
import { TaggerTagList } from './TaggerTagList'

export function TaggerConfiguration({ tagger }: { tagger: TaggerApi }): JSX.Element {
    const config = tagger.tagger_config
    const isHog = tagger.tagger_type === 'hog'
    const tags = config.tags ?? []

    return (
        <div className="space-y-6 max-w-3xl">
            {tagger.description && <TaggerConfigField label="Description">{tagger.description}</TaggerConfigField>}

            <TaggerConfigField label="Method">{isHog ? 'Hog code' : 'LLM'}</TaggerConfigField>

            {'source' in config ? (
                <TaggerConfigField label="Hog code">
                    <CodeSnippet language={Language.Text} thing="Hog code">
                        {config.source}
                    </CodeSnippet>
                </TaggerConfigField>
            ) : (
                <TaggerConfigField label="Prompt">
                    <CodeSnippet language={Language.Text} wrap thing="prompt">
                        {config.prompt}
                    </CodeSnippet>
                </TaggerConfigField>
            )}

            <TaggerConfigField label="Tags">
                <TaggerTagList tags={tags} />
            </TaggerConfigField>

            {'prompt' in config && (
                <>
                    <TaggerConfigField label="Tags per generation">
                        {config.min_tags ?? 0} to {config.max_tags ?? 'any number'}
                    </TaggerConfigField>
                    {tagger.model_configuration && (
                        <TaggerConfigField label="Model">
                            {providerLabel(tagger.model_configuration.provider)} {tagger.model_configuration.model}
                            {tagger.model_configuration.provider_key_name && (
                                <span className="text-muted">
                                    {' '}
                                    (key: {tagger.model_configuration.provider_key_name})
                                </span>
                            )}
                        </TaggerConfigField>
                    )}
                </>
            )}

            <TaggerConfigField label="Conditions">
                <div className="space-y-2">
                    {tagger.conditions.map((condition, index) => (
                        <TaggerConditionRow key={condition.id} condition={condition} index={index} />
                    ))}
                </div>
            </TaggerConfigField>
        </div>
    )
}
