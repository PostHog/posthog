import { useValues } from 'kea'
import { useState } from 'react'

import { IconExternal, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, LemonModal, LemonSelect, LemonTextArea, Link, lemonToast } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { DARK_MODE_INVERT_ICON_KINDS, ICONS } from 'lib/integrations/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import api from '~/lib/api'
import { IntegrationKind } from '~/types'

import { Ticket, TicketExternalReference } from '../../types'

const SUPPORTED_INTEGRATION_KINDS: IntegrationKind[] = ['github', 'linear', 'jira', 'gitlab']

interface LinkedIssuesPanelProps {
    ticket: Ticket
    onReferencesChange?: (references: TicketExternalReference[]) => void
}

export function LinkedIssuesPanel({ ticket, onReferencesChange }: LinkedIssuesPanelProps): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const [references, setReferences] = useState<TicketExternalReference[]>(ticket.external_references || [])
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [modalTab, setModalTab] = useState<'link' | 'create'>('create')

    // Form states
    const [selectedIntegrationId, setSelectedIntegrationId] = useState<number | null>(null)
    const [repository, setRepository] = useState('')
    const [title, setTitle] = useState(ticket.email_subject || `Support Ticket #${ticket.ticket_number}`)
    const [body, setBody] = useState(
        ticket.last_message_text
            ? `Customer reported in Support Ticket #${ticket.ticket_number}:\n\n> ${ticket.last_message_text}`
            : `Support Ticket #${ticket.ticket_number}`
    )
    const [searchQuery, setSearchQuery] = useState('')
    const [searchResults, setSearchResults] = useState<any[]>([])
    const [searching, setSearching] = useState(false)
    const [submitting, setSubmitting] = useState(false)

    const availableIntegrations = getIntegrationsByKind(SUPPORTED_INTEGRATION_KINDS)

    const currentTeamId = getCurrentTeamId()

    // Default to first available integration if none selected
    const activeIntegration =
        availableIntegrations.find((i) => i.id === selectedIntegrationId) || availableIntegrations[0]

    const handleSearch = async (): Promise<void> => {
        if (!activeIntegration) {
            return
        }
        setSearching(true)
        try {
            const params: Record<string, any> = {
                integration_id: activeIntegration.id,
                search: searchQuery,
            }
            if (activeIntegration.kind === 'github' && repository) {
                params.repository = repository
            }
            const res = await api.get(
                `api/projects/${currentTeamId}/conversations/external_references/search_issues/?${new URLSearchParams(
                    params
                )}`
            )
            setSearchResults(res.issues || [])
        } catch (err: any) {
            lemonToast.error(err.detail || err.message || 'Failed to search issues')
        } finally {
            setSearching(false)
        }
    }

    const handleCreate = async (): Promise<void> => {
        if (!activeIntegration) {
            lemonToast.error('Please select an integration')
            return
        }
        if (activeIntegration.kind === 'github' && !repository.trim()) {
            lemonToast.error('Please enter a GitHub repository')
            return
        }
        if (!title.trim()) {
            lemonToast.error('Please enter an issue title')
            return
        }

        setSubmitting(true)
        try {
            const config: Record<string, string> = {
                title: title.trim(),
            }
            if (activeIntegration.kind === 'github') {
                config.repository = repository.trim()
                config.body = body.trim()
            } else if (activeIntegration.kind === 'gitlab') {
                config.body = body.trim()
            } else if (activeIntegration.kind === 'linear' || activeIntegration.kind === 'jira') {
                config.description = body.trim()
            }

            const newRef = await api.create(`api/projects/${currentTeamId}/conversations/external_references/`, {
                ticket: ticket.id,
                integration_id: activeIntegration.id,
                config,
            })

            const updated = [...references, newRef]
            setReferences(updated)
            onReferencesChange?.(updated)
            lemonToast.success('Created and linked issue successfully')
            setIsModalOpen(false)
        } catch (err: any) {
            lemonToast.error(err.detail || err.message || 'Failed to create issue')
        } finally {
            setSubmitting(false)
        }
    }

    const handleLinkExisting = async (issueResult: any): Promise<void> => {
        if (!activeIntegration) {
            return
        }
        setSubmitting(true)
        try {
            const newRef = await api.create(
                `api/projects/${currentTeamId}/conversations/external_references/link_issue/`,
                {
                    ticket: ticket.id,
                    integration_id: activeIntegration.id,
                    external_context: issueResult.external_context,
                }
            )

            const updated = references.some((r) => r.id === newRef.id) ? references : [...references, newRef]
            setReferences(updated)
            onReferencesChange?.(updated)
            lemonToast.success('Linked issue successfully')
            setIsModalOpen(false)
        } catch (err: any) {
            lemonToast.error(err.detail || err.message || 'Failed to link issue')
        } finally {
            setSubmitting(false)
        }
    }

    const handleDelete = async (referenceId: string): Promise<void> => {
        try {
            await api.delete(`api/projects/${currentTeamId}/conversations/external_references/${referenceId}/`)
            const updated = references.filter((r) => r.id !== referenceId)
            setReferences(updated)
            onReferencesChange?.(updated)
            lemonToast.success('Removed link')
        } catch (err: any) {
            lemonToast.error(err.detail || err.message || 'Failed to remove link')
        }
    }

    return (
        <>
            <LemonCollapse
                className="bg-surface-primary"
                defaultActiveKey="linked-issues"
                panels={[
                    {
                        key: 'linked-issues',
                        header: (
                            <div className="flex items-center justify-between w-full pr-2">
                                <span className="font-semibold text-xs">
                                    Linked issues {references.length > 0 && `(${references.length})`}
                                </span>
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    icon={<IconPlus />}
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        setIsModalOpen(true)
                                    }}
                                >
                                    Link
                                </LemonButton>
                            </div>
                        ),
                        content: (
                            <div className="space-y-2">
                                {references.length === 0 ? (
                                    <div className="text-xs text-muted-alt py-1">
                                        No linked GitHub or external issues.
                                    </div>
                                ) : (
                                    <div className="divide-y divide-border">
                                        {references.map((ref) => {
                                            const kind = ref.integration?.kind as IntegrationKind
                                            const icon = ICONS[kind]
                                            const isDarkModeInvert = DARK_MODE_INVERT_ICON_KINDS.has(kind)

                                            return (
                                                <div
                                                    key={ref.id}
                                                    className="py-2 flex items-center justify-between gap-2 text-xs"
                                                >
                                                    <div className="flex items-center gap-2 min-w-0">
                                                        {icon && (
                                                            <img
                                                                src={icon}
                                                                alt={kind}
                                                                className={`w-4 h-4 shrink-0 rounded-sm ${
                                                                    isDarkModeInvert ? 'dark:invert' : ''
                                                                }`}
                                                            />
                                                        )}
                                                        <Link
                                                            to={ref.external_url}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            className="truncate font-medium flex items-center gap-1 text-primary hover:underline"
                                                            title={ref.title || ref.external_id}
                                                        >
                                                            <span>
                                                                {ref.external_id ? `#${ref.external_id} ` : ''}
                                                                {ref.title || 'Linked issue'}
                                                            </span>
                                                            <IconExternal className="shrink-0 text-muted" />
                                                        </Link>
                                                    </div>
                                                    <LemonButton
                                                        size="xsmall"
                                                        status="danger"
                                                        icon={<IconTrash />}
                                                        onClick={() => handleDelete(ref.id)}
                                                        title="Unlink issue"
                                                    />
                                                </div>
                                            )
                                        })}
                                    </div>
                                )}
                            </div>
                        ),
                    },
                ]}
            />

            <LemonModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                title="Link or create external issue"
                width="36rem"
                footer={
                    modalTab === 'create' ? (
                        <div className="flex justify-end gap-2">
                            <LemonButton type="secondary" onClick={() => setIsModalOpen(false)}>
                                Cancel
                            </LemonButton>
                            <LemonButton type="primary" loading={submitting} onClick={handleCreate}>
                                Create & link issue
                            </LemonButton>
                        </div>
                    ) : (
                        <LemonButton type="secondary" onClick={() => setIsModalOpen(false)}>
                            Close
                        </LemonButton>
                    )
                }
            >
                <div className="space-y-4">
                    {availableIntegrations.length === 0 && !integrationsLoading ? (
                        <div className="text-sm text-muted">
                            No issue integrations connected. Connect GitHub, Linear, Jira, or GitLab in{' '}
                            <Link to="/settings/integrations">Settings → Integrations</Link>.
                        </div>
                    ) : (
                        <>
                            <div className="flex gap-2 border-b pb-2">
                                <LemonButton
                                    type={modalTab === 'create' ? 'primary' : 'secondary'}
                                    size="small"
                                    onClick={() => setModalTab('create')}
                                >
                                    Create new issue
                                </LemonButton>
                                <LemonButton
                                    type={modalTab === 'link' ? 'primary' : 'secondary'}
                                    size="small"
                                    onClick={() => setModalTab('link')}
                                >
                                    Link existing issue
                                </LemonButton>
                            </div>

                            <div>
                                <label className="text-xs font-semibold block mb-1">Integration provider</label>
                                <LemonSelect
                                    value={activeIntegration?.id}
                                    onChange={(id) => setSelectedIntegrationId(id)}
                                    options={availableIntegrations.map((i) => ({
                                        value: i.id,
                                        label: `${i.kind.toUpperCase()} - ${i.name || i.config?.account?.name || 'Connected'}`,
                                    }))}
                                    fullWidth
                                />
                            </div>

                            {modalTab === 'create' ? (
                                <div className="space-y-3">
                                    {activeIntegration?.kind === 'github' && (
                                        <div>
                                            <label className="text-xs font-semibold block mb-1">
                                                GitHub Repository (owner/repo or repo)
                                            </label>
                                            <LemonInput
                                                value={repository}
                                                onChange={setRepository}
                                                placeholder="e.g. posthog or PostHog/posthog"
                                                fullWidth
                                            />
                                        </div>
                                    )}

                                    <div>
                                        <label className="text-xs font-semibold block mb-1">Issue title</label>
                                        <LemonInput
                                            value={title}
                                            onChange={setTitle}
                                            placeholder="Issue title"
                                            fullWidth
                                        />
                                    </div>

                                    <div>
                                        <label className="text-xs font-semibold block mb-1">Description / Body</label>
                                        <LemonTextArea
                                            value={body}
                                            onChange={setBody}
                                            rows={4}
                                            placeholder="Issue description"
                                        />
                                        <span className="text-xs text-muted-alt">
                                            A permalink back to this Support Ticket will be automatically attached.
                                        </span>
                                    </div>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {activeIntegration?.kind === 'github' && (
                                        <div>
                                            <label className="text-xs font-semibold block mb-1">
                                                Repository to search
                                            </label>
                                            <LemonInput
                                                value={repository}
                                                onChange={setRepository}
                                                placeholder="e.g. posthog"
                                                fullWidth
                                            />
                                        </div>
                                    )}

                                    <div>
                                        <label className="text-xs font-semibold block mb-1">Search issue</label>
                                        <div className="flex gap-2">
                                            <LemonInput
                                                value={searchQuery}
                                                onChange={setSearchQuery}
                                                placeholder="Search issue title or number..."
                                                fullWidth
                                                onPressEnter={handleSearch}
                                            />
                                            <LemonButton
                                                type="secondary"
                                                loading={searching}
                                                onClick={handleSearch}
                                            >
                                                Search
                                            </LemonButton>
                                        </div>
                                    </div>

                                    <div className="space-y-2 max-h-60 overflow-y-auto pt-2">
                                        {searchResults.length === 0 ? (
                                            <div className="text-xs text-muted-alt text-center py-4">
                                                {searching ? 'Searching...' : 'Search for an issue to link.'}
                                            </div>
                                        ) : (
                                            searchResults.map((issue) => (
                                                <div
                                                    key={issue.id}
                                                    className="flex items-center justify-between p-2 border rounded hover:bg-surface-secondary text-xs"
                                                >
                                                    <div className="truncate mr-2">
                                                        <span className="font-semibold mr-1">#{issue.id}</span>
                                                        <span>{issue.title}</span>
                                                    </div>
                                                    <LemonButton
                                                        size="xsmall"
                                                        type="primary"
                                                        loading={submitting}
                                                        onClick={() => handleLinkExisting(issue)}
                                                    >
                                                        Link
                                                    </LemonButton>
                                                </div>
                                            ))
                                        )}
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </div>
            </LemonModal>
        </>
    )
}
