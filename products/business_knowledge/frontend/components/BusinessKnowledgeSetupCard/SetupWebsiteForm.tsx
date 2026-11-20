import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconGlobe } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { businessKnowledgeLogic } from '../../scenes/sources/businessKnowledgeLogic'
import { DEFAULT_MAX_PAGES } from '../../sourceFormUtils'
import { businessKnowledgeSetupCardLogic } from './businessKnowledgeSetupCardLogic'

export function SetupWebsiteForm({ mode, preview }: { mode: ProductEmptyStateMode; preview: boolean }): JSX.Element {
    const { urlSource, isUrlSourceSubmitting } = useValues(businessKnowledgeLogic)
    const { suggestedWebsite } = useValues(businessKnowledgeSetupCardLogic)
    const { submitWebsite, pickSource } = useActions(businessKnowledgeSetupCardLogic)

    const showsSuggestion = !!suggestedWebsite && urlSource.url === suggestedWebsite

    return (
        <Form logic={businessKnowledgeLogic} formKey="urlSource" className="flex flex-col gap-2 px-4 py-3">
            <LemonField name="url" label="Start with your website">
                {({ value, onChange }) => (
                    <div className="flex flex-wrap gap-2">
                        <LemonInput
                            className="min-w-48 flex-1"
                            prefix={<IconGlobe />}
                            inputMode="url"
                            autoComplete="url"
                            placeholder="https://example.com"
                            value={value}
                            onChange={onChange}
                            onPressEnter={() => submitWebsite(mode, preview)}
                            disabledReason={isUrlSourceSubmitting ? 'Adding your website' : undefined}
                            data-attr="business-knowledge-setup-website-url"
                        />
                        <LemonButton
                            type="primary"
                            loading={isUrlSourceSubmitting}
                            onClick={() => submitWebsite(mode, preview)}
                            data-attr="business-knowledge-setup-website-submit"
                        >
                            Add website
                        </LemonButton>
                    </div>
                )}
            </LemonField>
            <span className="text-xs text-secondary">
                {showsSuggestion
                    ? 'We found this address in your recent pageviews. Change it if your docs are on another site. '
                    : null}
                PostHog indexes this page and the pages under it, up to {DEFAULT_MAX_PAGES} pages.{' '}
                <Link
                    onClick={() => pickSource('url', mode, preview)}
                    // pinned: the attr the website row carried before the form replaced it.
                    data-attr="business-knowledge-setup-source-url"
                >
                    More options
                </Link>
            </span>
        </Form>
    )
}
