import { useActions } from 'kea'
import { combineUrl } from 'kea-router'

import { IconChevronRight, IconDocument, IconGithub, IconPencil, IconSupport } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { REFRESH_INTERVAL_OPTIONS } from '../../scenes/sources/businessKnowledgeLogic'
import { CreateKnowledgeSourceModal } from '../CreateKnowledgeSourceModal/CreateKnowledgeSourceModal'
import { type BusinessKnowledgeSetupSource, businessKnowledgeSetupCardLogic } from './businessKnowledgeSetupCardLogic'
import { SetupWebsiteForm } from './SetupWebsiteForm'

interface SetupSource {
    key: BusinessKnowledgeSetupSource
    icon: JSX.Element
    title: string
    description: string
}

const OTHER_SOURCES: SetupSource[] = [
    {
        key: 'file',
        icon: <IconDocument />,
        title: 'File',
        description: 'Upload a PDF, DOCX, Markdown, CSV, or plain text file.',
    },
    {
        key: 'text',
        icon: <IconPencil />,
        title: 'Text',
        description: 'Paste a policy, an FAQ, or notes that are not written down anywhere else.',
    },
    {
        key: 'github',
        icon: <IconGithub />,
        title: 'GitHub repositories',
        description: 'Let agents read the README and files in the repositories you choose.',
    },
    {
        key: 'support',
        icon: <IconSupport />,
        title: 'Resolved support tickets',
        description: "Learn reusable answers from your team's replies on resolved tickets.",
    },
]

/**
 * The gate replaces the scene, so the create modal the scene normally renders never mounts.
 * The card renders it, or the source rows would open nothing.
 */
export function BusinessKnowledgeSetupCard({
    mode,
    preview,
}: {
    mode: ProductEmptyStateMode
    preview: boolean
}): JSX.Element {
    const { pickSource } = useActions(businessKnowledgeSetupCardLogic)
    const canConnectAgent = useFeatureFlag('BUSINESS_KNOWLEDGE_MCP')

    return (
        <>
            <div className="mt-2 flex flex-col overflow-hidden rounded border border-primary bg-surface-primary">
                <div className="flex flex-col gap-1 px-4 pb-3 pt-3.5">
                    <span className="text-base font-semibold">
                        {canConnectAgent ? '1. Add your knowledge' : 'Choose what your agents learn from'}
                    </span>
                    <span className="text-sm text-secondary">
                        Add one source to start. You can add more sources later.
                    </span>
                </div>
                <div className="border-t border-primary">
                    <SetupWebsiteForm mode={mode} preview={preview} />
                </div>
                <span className="border-t border-primary px-4 pb-1 pt-3 text-xs font-semibold text-secondary">
                    Or add another source
                </span>
                <div className="flex flex-col gap-px p-1">
                    {OTHER_SOURCES.map((source) => (
                        <LemonButton
                            key={source.key}
                            fullWidth
                            icon={source.icon}
                            sideIcon={<IconChevronRight className="size-3" />}
                            onClick={() => pickSource(source.key, mode, preview)}
                            data-attr={`business-knowledge-setup-source-${source.key}`}
                        >
                            <span className="flex min-w-0 flex-col py-0.5 text-left">
                                <span className="font-semibold">{source.title}</span>
                                <span className="whitespace-normal text-xs font-normal text-secondary">
                                    {source.description}
                                </span>
                            </span>
                        </LemonButton>
                    ))}
                </div>
                <CreateKnowledgeSourceModal refreshIntervalOptions={REFRESH_INTERVAL_OPTIONS} />
            </div>
            {canConnectAgent && (
                <div className="mt-2 flex flex-col gap-1 rounded border border-primary bg-surface-primary px-4 pb-3 pt-3.5">
                    <span className="text-base font-semibold">2. Connect your agent</span>
                    <span className="text-sm text-secondary">
                        Your agent reads this knowledge through the PostHog MCP server. Give each agent a key for one
                        library, so a public help desk reads only your public docs.{' '}
                        <Link
                            to={
                                combineUrl(
                                    urls.businessKnowledgeSettings(),
                                    {},
                                    // pinned: setting id from the settings map.
                                    { selectedSetting: 'business-knowledge-connect-agent' }
                                ).url
                            }
                            data-attr="business-knowledge-setup-connect-agent"
                        >
                            See how to connect
                        </Link>
                    </span>
                </div>
            )}
        </>
    )
}
