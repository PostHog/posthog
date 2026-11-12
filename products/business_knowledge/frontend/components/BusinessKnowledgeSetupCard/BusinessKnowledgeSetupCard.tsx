import { useActions } from 'kea'

import { IconChevronRight, IconDocument, IconGithub, IconGlobe, IconPencil, IconSupport } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'

import { REFRESH_INTERVAL_OPTIONS } from '../../scenes/sources/businessKnowledgeLogic'
import { CreateKnowledgeSourceModal } from '../CreateKnowledgeSourceModal/CreateKnowledgeSourceModal'
import { type BusinessKnowledgeSetupSource, businessKnowledgeSetupCardLogic } from './businessKnowledgeSetupCardLogic'

interface SetupSource {
    key: BusinessKnowledgeSetupSource
    icon: JSX.Element
    title: string
    description: string
}

const SOURCES: SetupSource[] = [
    {
        key: 'url',
        icon: <IconGlobe />,
        title: 'Website',
        description: 'Index a page, a sitemap, or a whole docs site, and refresh it on a schedule.',
    },
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

    return (
        <div className="mt-2 flex flex-col overflow-hidden rounded border border-primary bg-surface-primary">
            <div className="flex flex-col gap-1 px-4 pb-3 pt-3.5">
                <span className="text-base font-semibold">Choose what your agents learn from</span>
                <span className="text-sm text-secondary">Pick a source to add it. You can add more sources later.</span>
            </div>
            <div className="flex flex-col gap-px border-t border-primary p-1">
                {SOURCES.map((source) => (
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
    )
}
