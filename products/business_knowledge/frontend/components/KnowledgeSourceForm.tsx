import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import type { RefreshIntervalOption } from '../api'
import { knowledgeSourceLogic } from '../scenes/knowledgeSourceLogic'
import { AlwaysIncludeField } from './AlwaysIncludeField'
import { CrawlConfigFields } from './CrawlConfigFields'

export function KnowledgeSourceForm({
    refreshIntervalOptions,
}: {
    refreshIntervalOptions: RefreshIntervalOption[]
}): JSX.Element {
    const { source, isSourceTextReady, sourceTextFailed, editUrlSource } = useValues(knowledgeSourceLogic)
    const { loadSourceText } = useActions(knowledgeSourceLogic)

    if (source?.source_type === 'url') {
        return (
            <Form logic={knowledgeSourceLogic} formKey="editUrlSource" className="flex flex-col gap-2">
                <LemonField name="name" label="Name">
                    <LemonInput />
                </LemonField>
                <LemonField name="url" label="URL">
                    <LemonInput placeholder="https://docs.example.com" />
                </LemonField>
                <LemonField name="crawl_mode" label="Crawl mode">
                    <LemonSelect
                        options={[
                            { value: 'single', label: 'Single page' },
                            { value: 'sitemap', label: 'Sitemap' },
                            { value: 'same_origin', label: 'Crawl same origin' },
                        ]}
                    />
                </LemonField>
                <CrawlConfigFields crawlMode={editUrlSource.crawl_mode} url={editUrlSource.url} />
                <LemonField
                    name="refresh_interval"
                    label="Auto-refresh"
                    info="How often PostHog re-fetches this source in the background. Changing it alone does not trigger an immediate re-crawl."
                >
                    <LemonSelect options={refreshIntervalOptions} />
                </LemonField>
                <AlwaysIncludeField />
                <p className="text-xs text-muted">Changing the URL or crawl settings will trigger a re-crawl.</p>
            </Form>
        )
    }

    if (source?.source_type === 'text' && !isSourceTextReady) {
        return (
            <div className="flex flex-col gap-2">
                <LemonSkeleton className="h-10" />
                <LemonSkeleton className="h-60" />
            </div>
        )
    }

    return (
        <Form logic={knowledgeSourceLogic} formKey="editSource" className="flex flex-col gap-2">
            {sourceTextFailed && (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadSourceText }}>
                    Couldn't load this source's content. You can still save the name.
                </LemonBanner>
            )}
            <LemonField name="name" label="Name">
                <LemonInput />
            </LemonField>
            {source?.source_type === 'text' && !sourceTextFailed && (
                <LemonField name="text" label="Content">
                    <LemonTextArea minRows={12} />
                </LemonField>
            )}
            {source?.source_type === 'file' && source.original_filename && (
                <p className="text-xs text-muted">
                    Uploaded file: {source.original_filename}. To replace the content, delete this source and upload a
                    new file.
                </p>
            )}
            {source?.source_type === 'text' && !sourceTextFailed && (
                <p className="text-xs text-muted">
                    Saving rewrites the chunks for this source. Agents won't see the change mid-conversation until they
                    refresh their prompt.
                </p>
            )}
            <AlwaysIncludeField />
        </Form>
    )
}
