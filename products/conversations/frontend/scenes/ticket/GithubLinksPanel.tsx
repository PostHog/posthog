import { useActions, useValues } from 'kea'

import { IconGithub, IconPullRequest, IconX } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonInput, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import type { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { urls } from 'scenes/urls'

import type { TicketGithubLinkApi } from '../../generated/api.schemas'
import { githubLinksLogic } from './githubLinksLogic'

interface GithubLinksPanelProps {
    ticketId: string
    /** When set, linking and unlinking are disabled and this explains why. */
    disabledReason?: string
}

const STATE_TAGS: Record<string, { label: string; type: LemonTagType }> = {
    open: { label: 'Open', type: 'success' },
    closed: { label: 'Closed', type: 'danger' },
    merged: { label: 'Merged', type: 'completion' },
}

function GithubLinkRow({
    link,
    removing,
    disabledReason,
    onRemove,
}: {
    link: TicketGithubLinkApi
    removing: boolean
    disabledReason?: string
    onRemove: () => void
}): JSX.Element {
    const isPullRequest = link.link_type === 'pull_request'
    const stateTag = link.link_state ? STATE_TAGS[link.link_state] : undefined
    return (
        <div className="flex items-start gap-2 min-w-0">
            <Tooltip title={isPullRequest ? 'Pull request' : 'Issue'}>
                <span className="text-muted-alt flex shrink-0 mt-0.5">
                    {isPullRequest ? <IconPullRequest /> : <IconGithub />}
                </span>
            </Tooltip>
            <div className="flex flex-col min-w-0 flex-1">
                <div className="flex items-center gap-2 min-w-0">
                    <Link to={link.url} target="_blank" className="text-xs truncate" title={link.url}>
                        {link.repo}#{link.number}
                    </Link>
                    <LemonTag type="muted" size="small" className="shrink-0">
                        {isPullRequest ? 'PR' : 'Issue'}
                    </LemonTag>
                    {stateTag && (
                        <LemonTag type={stateTag.type} size="small" className="shrink-0">
                            {stateTag.label}
                        </LemonTag>
                    )}
                </div>
                {link.title && (
                    <span className="text-xs text-secondary truncate" title={link.title}>
                        {link.title}
                    </span>
                )}
            </div>
            <LemonButton
                size="xxsmall"
                type="tertiary"
                icon={<IconX />}
                tooltip="Unlink"
                className="shrink-0"
                onClick={onRemove}
                loading={removing}
                disabledReason={disabledReason}
                data-attr="ticket-github-link-remove"
            />
        </div>
    )
}

export function GithubLinksPanel({ ticketId, disabledReason }: GithubLinksPanelProps): JSX.Element {
    const logic = githubLinksLogic({ ticketId })
    const { githubLinks, githubLinksLoading, newLinkUrl, linkSubmitting, removingLinkIds } = useValues(logic)
    const { setNewLinkUrl, addGithubLink, removeGithubLink } = useActions(logic)

    // Title and state only come back when a GitHub integration in this project can see the repo.
    const hasLinksWithoutMetadata = githubLinks.some((link) => !link.title && !link.link_state)

    let list: JSX.Element
    if (githubLinksLoading && githubLinks.length === 0) {
        list = <Spinner />
    } else if (githubLinks.length === 0) {
        list = <div className="text-xs text-secondary">No linked issues or pull requests yet.</div>
    } else {
        list = (
            <div className="space-y-1">
                {githubLinks.map((link) => (
                    <GithubLinkRow
                        key={link.id}
                        link={link}
                        removing={removingLinkIds.includes(link.id)}
                        disabledReason={disabledReason}
                        onRemove={() => removeGithubLink(link.id)}
                    />
                ))}
                {hasLinksWithoutMetadata && (
                    <div className="text-xs text-muted-alt pt-1">
                        Titles and status show when a{' '}
                        <Link to={urls.settings('environment-integrations')}>GitHub integration</Link> in this project
                        can see the repository.
                    </div>
                )}
            </div>
        )
    }

    return (
        <LemonCollapse
            className="bg-surface-primary"
            defaultActiveKey="github-links"
            panels={[
                {
                    key: 'github-links',
                    header: 'GitHub',
                    content: (
                        <div className="space-y-3">
                            {list}
                            <form
                                className="flex gap-2"
                                onSubmit={(e) => {
                                    e.preventDefault()
                                    addGithubLink()
                                }}
                            >
                                <LemonInput
                                    size="small"
                                    fullWidth
                                    value={newLinkUrl}
                                    onChange={setNewLinkUrl}
                                    placeholder="owner/repo#123 or GitHub URL"
                                    disabled={!!disabledReason || linkSubmitting}
                                    data-attr="ticket-github-link-url"
                                />
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    htmlType="submit"
                                    loading={linkSubmitting}
                                    disabledReason={
                                        disabledReason ??
                                        (!newLinkUrl.trim() ? 'Enter an issue or PR reference' : undefined)
                                    }
                                    data-attr="ticket-github-link-add"
                                >
                                    Link
                                </LemonButton>
                            </form>
                        </div>
                    ),
                },
            ]}
        />
    )
}
