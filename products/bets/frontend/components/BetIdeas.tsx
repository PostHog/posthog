import { useActions, useValues } from 'kea'

import { IconChevronDown, IconLightBulb, IconPlus, IconTelescope } from '@posthog/icons'
import { Button, Collapsible, CollapsibleContent, CollapsibleTrigger, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { TodayRow } from 'scenes/project-homepage/today/TodayRow'
import { urls } from 'scenes/urls'

import type { BetsDetailApi } from '../generated/api.schemas'
import { IDEA_ICON_COLOR, inProgressLabel, laterLabel, readyIdeas } from '../lib/ideas'
import { betLogic } from '../logics/betLogic'
import { BetAddIdeaForm } from './BetAddIdeaForm'
import { BetBuildDialog } from './BetBuildDialog'
import { BetIdeaRow } from './BetIdeaRow'
import { BetWorkStatusIcon } from './BetWorkStatusIcon'

export function BetIdeas({ bet }: { bet: BetsDetailApi }): JSX.Element | null {
    const {
        waitingIdeas,
        dismissedIdeas,
        ideaInProgress,
        addingIdea,
        ideaError,
        laterOpen,
        dismissedOpen,
        busy,
        buildDisabledReason,
    } = useValues(betLogic({ id: bet.id }))
    const { setAddingIdea, setLaterOpen, setDismissedOpen, setExpandedWork } = useActions(betLogic({ id: bet.id }))
    const canAdd = bet.is_owner && bet.status !== 'closed'
    const scoutRunning = !!bet.scout?.running
    if (!waitingIdeas.length && !dismissedIdeas.length && !canAdd && !scoutRunning && !ideaInProgress) {
        return null
    }
    const listOpen = !ideaInProgress || laterOpen
    const ready = readyIdeas(bet).length
    const summary = ready
        ? `${ready} ${ready === 1 ? 'idea waits' : 'ideas wait'} for your choice.`
        : waitingIdeas.length
          ? 'The Scout checks your ideas against your data before you choose.'
          : scoutRunning
            ? ''
            : bet.status === 'closed'
              ? 'No ideas wait for a choice.'
              : bet.next_action?.id.endsWith(':scout-empty')
                ? bet.next_action.description.split('\n\n')[0]
                : 'No ideas wait for a choice. The Scout looks for new ideas on its next run.'
    const blocked = bet.is_owner && waitingIdeas.length > 0 ? buildDisabledReason : null
    return (
        <section id="bet-ideas" className="flex min-w-0 flex-col gap-2 pb-2" aria-label="Ideas">
            <div className="flex flex-col gap-0.5">
                <div className="flex min-h-7 items-center justify-between gap-2">
                    <h2 className="Bets__sectionTitle">Ideas</h2>
                    <div className="flex items-center gap-3">
                        {bet.scout && (
                            <Button
                                size="sm"
                                variant="link-muted"
                                render={<LinkPrimitive to={urls.inboxScout(bet.scout.name)} />}
                                data-attr="bets-ideas-open-scout"
                            >
                                <IconTelescope />
                                View Scout
                            </Button>
                        )}
                        {canAdd && !addingIdea && (
                            <Button
                                size="sm"
                                variant="link-muted"
                                disabled={busy}
                                onClick={() => setAddingIdea(true)}
                                data-attr="bets-add-idea"
                            >
                                <IconPlus />
                                Add an idea
                            </Button>
                        )}
                    </div>
                </div>
                {ideaInProgress ? (
                    <Text size="sm" variant="muted" render={<p className="m-0 flex min-w-0 items-baseline" />}>
                        <span className="shrink-0">{inProgressLabel(ideaInProgress)}:&nbsp;</span>
                        <Button
                            size="inline"
                            variant="link-muted"
                            className="Bets__ideasBuilding block min-w-0 shrink truncate"
                            onClick={() => setExpandedWork(ideaInProgress.id)}
                            data-attr="bets-ideas-building"
                        >
                            {ideaInProgress.title}
                        </Button>
                        <span className="shrink-0">&nbsp;·&nbsp;</span>
                        {waitingIdeas.length || dismissedIdeas.length ? (
                            <Button
                                size="inline"
                                variant="link-muted"
                                className="shrink-0"
                                aria-expanded={laterOpen}
                                onClick={() => setLaterOpen(!laterOpen)}
                                data-attr="bets-ideas-later"
                            >
                                {waitingIdeas.length ? laterLabel(waitingIdeas.length) : 'Dismissed ideas'}
                                <IconChevronDown
                                    className={laterOpen ? 'Bets__ideasChevron rotate-180' : 'Bets__ideasChevron'}
                                />
                            </Button>
                        ) : (
                            <span className="shrink-0">New ideas come after its result</span>
                        )}
                    </Text>
                ) : (
                    (summary || blocked) && (
                        <Text size="sm" variant="muted" render={<p className="m-0" />}>
                            {[summary, blocked].filter(Boolean).join(' ')}
                        </Text>
                    )
                )}
            </div>
            {ideaError && (
                <Text size="sm" variant="destructive" render={<p role="alert" className="m-0" />}>
                    {ideaError}
                </Text>
            )}
            {addingIdea && <BetAddIdeaForm betId={bet.id} />}
            {scoutRunning && !ideaInProgress && (
                <div className="Bets__ideaRows flex flex-col">
                    <TodayRow
                        tone="neutral"
                        icon={{ color: 'var(--color-product-self-driving-light)', glyph: <IconTelescope /> }}
                        title={waitingIdeas.length ? 'Looking for more ideas' : 'Looking for ideas'}
                        facts={['Scout', 'Searching']}
                        statusIcon={<BetWorkStatusIcon status={{ label: 'Searching', mark: 'spinner' }} />}
                        to={bet.scout ? urls.inboxScout(bet.scout.name) : undefined}
                        dataAttr="bets-scout-row"
                    />
                </div>
            )}
            <Collapsible variant="folder" open={listOpen}>
                <CollapsibleContent className="flex flex-col gap-2 px-0 pb-0">
                    {waitingIdeas.length > 0 && (
                        <div className="Bets__ideaRows flex flex-col">
                            {waitingIdeas.map((item) => (
                                <BetIdeaRow key={item.id} item={item} bet={bet} />
                            ))}
                        </div>
                    )}
                    {dismissedIdeas.length > 0 && (
                        <Collapsible variant="folder" open={dismissedOpen} onOpenChange={setDismissedOpen}>
                            <CollapsibleTrigger className="Bets__ideaToggle" data-attr="bets-ideas-dismissed">
                                Dismissed ({dismissedIdeas.length})
                            </CollapsibleTrigger>
                            <CollapsibleContent className="px-0 pb-0">
                                <div className="Bets__ideaRows flex flex-col">
                                    {dismissedIdeas.map((item) => (
                                        <TodayRow
                                            key={item.id}
                                            tone="quiet"
                                            icon={{ color: IDEA_ICON_COLOR, glyph: <IconLightBulb /> }}
                                            title={item.title}
                                            facts={[item.dismissed_reason || 'Dismissed']}
                                            statusIcon={
                                                <BetWorkStatusIcon status={{ label: 'Dismissed', mark: 'cancelled' }} />
                                            }
                                            done
                                            dataAttr="bets-idea-dismissed"
                                        />
                                    ))}
                                </div>
                            </CollapsibleContent>
                        </Collapsible>
                    )}
                </CollapsibleContent>
            </Collapsible>
            <BetBuildDialog bet={bet} />
        </section>
    )
}
