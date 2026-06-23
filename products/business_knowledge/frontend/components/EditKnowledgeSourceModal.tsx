import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import type { RefreshIntervalOption } from '../api'
import { businessKnowledgeLogic } from '../scenes/businessKnowledgeLogic'
import { AlwaysIncludeField } from './AlwaysIncludeField'
import { CrawlConfigFields } from './CrawlConfigFields'

export function EditKnowledgeSourceModal({
    refreshIntervalOptions,
}: {
    refreshIntervalOptions: RefreshIntervalOption[]
}): JSX.Element {
    const {
        isEditModalOpen,
        editingSource,
        editingSourceTextLoading,
        isEditSourceSubmitting,
        isEditUrlSourceSubmitting,
        editUrlSource,
    } = useValues(businessKnowledgeLogic)
    const { closeEditModal, submitEditSource, submitEditUrlSource } = useActions(businessKnowledgeLogic)

    return (
        <LemonModal
            isOpen={isEditModalOpen}
            onClose={closeEditModal}
            title={editingSource ? `Edit "${editingSource.name}"` : 'Edit knowledge source'}
            footer={
                <>
                    <LemonButton onClick={closeEditModal}>Cancel</LemonButton>
                    <LemonButton
                        type="primary"
                        loading={
                            editingSource?.source_type === 'url' ? isEditUrlSourceSubmitting : isEditSourceSubmitting
                        }
                        disabled={editingSource?.source_type === 'text' && editingSourceTextLoading}
                        onClick={editingSource?.source_type === 'url' ? submitEditUrlSource : submitEditSource}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            {editingSource?.source_type === 'url' ? (
                <Form logic={businessKnowledgeLogic} formKey="editUrlSource" className="flex flex-col gap-2">
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
            ) : editingSource?.source_type === 'text' && editingSourceTextLoading ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-10" />
                    <LemonSkeleton className="h-60" />
                </div>
            ) : (
                <Form logic={businessKnowledgeLogic} formKey="editSource" className="flex flex-col gap-2">
                    <LemonField name="name" label="Name">
                        <LemonInput />
                    </LemonField>
                    {editingSource?.source_type === 'text' && (
                        <LemonField name="text" label="Content">
                            <LemonTextArea minRows={12} />
                        </LemonField>
                    )}
                    {editingSource?.source_type === 'file' && editingSource.original_filename && (
                        <p className="text-xs text-muted">
                            Uploaded file: {editingSource.original_filename}. To replace the content, delete this source
                            and upload a new file.
                        </p>
                    )}
                    {editingSource?.source_type === 'text' && (
                        <p className="text-xs text-muted">
                            Saving rewrites the chunks for this source. Agents won't see the change mid-conversation
                            until they refresh their prompt.
                        </p>
                    )}
                    <AlwaysIncludeField />
                </Form>
            )}
        </LemonModal>
    )
}
