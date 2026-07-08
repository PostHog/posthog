import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import type { RefreshIntervalOption } from '../api'
import { CreateTab, businessKnowledgeLogic } from '../scenes/businessKnowledgeLogic'
import { AlwaysIncludeField } from './AlwaysIncludeField'
import { CrawlConfigFields } from './CrawlConfigFields'
import { CrawlModeHelp } from './CrawlModeHelp'

export function CreateKnowledgeSourceModal({
    refreshIntervalOptions,
}: {
    refreshIntervalOptions: RefreshIntervalOption[]
}): JSX.Element {
    const {
        isCreateModalOpen,
        createTab,
        isTextSourceSubmitting,
        isUrlSourceSubmitting,
        isFileSourceSubmitting,
        urlSource,
    } = useValues(businessKnowledgeLogic)
    const { closeCreateModal, setCreateTab, submitTextSource, submitUrlSource, submitFileSource, setFileSourceValue } =
        useActions(businessKnowledgeLogic)

    return (
        <LemonModal
            isOpen={isCreateModalOpen}
            onClose={closeCreateModal}
            width={800}
            title="Add to business knowledge"
            footer={
                <>
                    <LemonButton onClick={closeCreateModal}>Cancel</LemonButton>
                    {createTab === 'text' ? (
                        <LemonButton type="primary" loading={isTextSourceSubmitting} onClick={submitTextSource}>
                            Add
                        </LemonButton>
                    ) : createTab === 'url' ? (
                        <LemonButton type="primary" loading={isUrlSourceSubmitting} onClick={submitUrlSource}>
                            Fetch and index
                        </LemonButton>
                    ) : (
                        <LemonButton type="primary" loading={isFileSourceSubmitting} onClick={submitFileSource}>
                            Upload and index
                        </LemonButton>
                    )}
                </>
            }
        >
            <LemonTabs
                activeKey={createTab}
                onChange={(key) => setCreateTab(key as CreateTab)}
                tabs={[
                    {
                        key: 'text',
                        label: 'Text',
                        content: (
                            <Form logic={businessKnowledgeLogic} formKey="textSource" className="flex flex-col gap-2">
                                <LemonField name="name" label="Name">
                                    <LemonInput placeholder="e.g. Refund policy" />
                                </LemonField>
                                <LemonField name="text" label="Content">
                                    <LemonTextArea
                                        placeholder="Paste FAQ, macros, or any text the support agent should be able to cite."
                                        minRows={12}
                                    />
                                </LemonField>
                                <p className="text-xs text-muted">
                                    Text is chunked paragraph-by-paragraph and stored in Postgres. The support agent can
                                    find it via SQL — no embeddings or vector DB in this stage.
                                </p>
                                <AlwaysIncludeField />
                            </Form>
                        ),
                    },
                    {
                        key: 'url',
                        label: 'URL',
                        content: (
                            <Form logic={businessKnowledgeLogic} formKey="urlSource" className="flex flex-col gap-2">
                                <LemonField name="name" label="Name">
                                    <LemonInput placeholder="e.g. Product docs – Billing" />
                                </LemonField>
                                <LemonField name="url" label="Entry URL">
                                    <LemonInput
                                        type="url"
                                        inputMode="url"
                                        placeholder="https://docs.example.com/billing or https://example.com/sitemap.xml"
                                    />
                                </LemonField>
                                <LemonField name="crawl_mode" label="Mode">
                                    <LemonSelect
                                        options={[
                                            {
                                                value: 'single',
                                                label: 'Single page',
                                            },
                                            {
                                                value: 'sitemap',
                                                label: 'Sitemap.xml',
                                            },
                                            {
                                                value: 'same_origin',
                                                label: 'Same-origin crawl',
                                            },
                                        ]}
                                    />
                                </LemonField>
                                <CrawlModeHelp />
                                <CrawlConfigFields crawlMode={urlSource.crawl_mode} url={urlSource.url} />
                                <LemonField
                                    name="refresh_interval"
                                    label="Auto-refresh"
                                    info="How often PostHog re-fetches this source in the background after the initial crawl."
                                >
                                    <LemonSelect options={refreshIntervalOptions} />
                                </LemonField>
                                <AlwaysIncludeField />
                            </Form>
                        ),
                    },
                    {
                        key: 'file',
                        label: 'File',
                        content: (
                            <Form logic={businessKnowledgeLogic} formKey="fileSource" className="flex flex-col gap-2">
                                <LemonField name="file" label="File">
                                    <LemonFileInput
                                        accept=".pdf,.docx,.md,.markdown,.txt,.csv"
                                        multiple={false}
                                        callToAction="Drop a file here or click to browse"
                                        showUploadedFiles
                                        onChange={(files) => {
                                            const file = files[0] ?? null
                                            setFileSourceValue('file', file)
                                            if (file) {
                                                const nameWithoutExt = file.name.replace(/\.[^.]+$/, '')
                                                setFileSourceValue('name', nameWithoutExt)
                                            }
                                        }}
                                    />
                                </LemonField>
                                <LemonField name="name" label="Name">
                                    <LemonInput placeholder="Auto-filled from filename" />
                                </LemonField>
                                <p className="text-xs text-muted">
                                    PDF, DOCX, Markdown, CSV, or plain text. Max 50 MB. The file is parsed into text and
                                    chunked — the original file is not stored.
                                </p>
                                <AlwaysIncludeField />
                            </Form>
                        ),
                    },
                ]}
            />
        </LemonModal>
    )
}
