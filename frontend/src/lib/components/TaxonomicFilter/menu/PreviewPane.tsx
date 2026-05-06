/**
 * Preview pane — right column of the combobox panel. Shows metadata for
 * the currently highlighted row (description, property type, sent-as,
 * pin / view, action match groups). Hidden on narrow viewports
 * (`md:flex`); list takes the full popover on mobile.
 *
 * Quill-native re-render of the legacy
 * `lib/components/DefinitionPopover/DefinitionPopoverContents.tsx`.
 * Properties / events / actions render specific extras; everything else
 * falls back to the shared header + description.
 */
import { Pin } from 'lucide-react'

import { Button, cn, ScrollArea, Separator } from '@posthog/quill'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ActionType, CohortType, EventDefinition, PropertyDefinition } from '~/types'

import { useTaxonomicAutocompleteItemDetails } from '../headless'
import { TaxonomicFilterGroupType } from '../types'
import { ActionMatchGroups } from './preview/ActionMatchGroups'
import { MenuFilterEntry } from './types'

export interface PreviewPaneProps {
    /** Highlighted entry, or `null` when nothing is highlighted. */
    entry: MenuFilterEntry | null
    className?: string
}

export function PreviewPane({ entry, className }: PreviewPaneProps): JSX.Element {
    return (
        <div className={cn('min-w-0 min-h-0', className)} data-slot="menu-filter-preview" aria-live="polite">
            {entry ? <PreviewBody entry={entry} /> : <PreviewEmpty />}
        </div>
    )
}

function PreviewEmpty(): JSX.Element {
    return (
        <div className="flex flex-1 items-center justify-center p-4 text-xs text-secondary text-center">
            Highlight an item to see details.
        </div>
    )
}

function PreviewBody({ entry }: { entry: MenuFilterEntry }): JSX.Element | null {
    const details = useTaxonomicAutocompleteItemDetails(entry)
    if (!details) {
        return null
    }

    // Action-specific match groups (`steps`) live on the entry's item, not
    // in the shared hook — the hook only models scalar metadata. Same
    // for event first/last seen (handled later if needed).
    const isAction = entry.group.type === TaxonomicFilterGroupType.Actions
    const viewUrl = resolveViewUrl(entry)

    return (
        <ScrollArea className="flex-1 min-h-0">
            <div className="flex flex-col gap-3 p-3 text-sm">
                <PreviewHeader details={details} viewUrl={viewUrl} />

                {details.description ? (
                    <p className="text-xs leading-relaxed text-secondary">{details.description}</p>
                ) : (
                    <p className="text-xs italic text-tertiary">No description.</p>
                )}

                {details.example && <p className="text-xs italic text-secondary">Example: {details.example}</p>}

                {details.propertyType && (
                    <div className="flex flex-col gap-0.5 border-t pt-2">
                        <div className="text-xxs uppercase tracking-wide text-secondary">Property type</div>
                        <div className="text-xs">{details.propertyType}</div>
                    </div>
                )}

                {details.rawName && details.rawName !== details.title && (
                    <div className="flex flex-col gap-0.5 border-t pt-2">
                        <div className="text-xxs uppercase tracking-wide text-secondary">Sent as</div>
                        <code className="text-xs break-all font-mono">{details.rawName}</code>
                    </div>
                )}

                {isAction && <ActionMatchGroups item={entry.item} />}
            </div>
        </ScrollArea>
    )
}

interface PreviewHeaderProps {
    details: ReturnType<typeof useTaxonomicAutocompleteItemDetails>
    /** Data management URL for the definition, or `undefined` to hide. */
    viewUrl: string | undefined
}

function PreviewHeader({ details, viewUrl }: PreviewHeaderProps): JSX.Element | null {
    if (!details) {
        return null
    }
    return (
        <div className="flex flex-col gap-4 " data-quill="true">
            <div className="flex items-center justify-between gap-2">
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={!details.isPinnable}
                    aria-pressed={details.isPinned}
                    onClick={details.togglePin}
                >
                    <Pin className="size-3.5" />
                    {details.isPinned ? 'Pinned' : 'Pin'}
                </Button>
                {viewUrl && (
                    <Button
                        variant="link"
                        className="text-primary"
                        size="sm"
                        render={<Link to={viewUrl} target="_blank" className="text-xs underline" />}
                    >
                        View
                    </Button>
                )}
            </div>
            <div className="flex flex-col gap-1">
                <div className="text-xxs uppercase tracking-wide text-secondary">{details.groupLabel}</div>
                <div className="text-base font-semibold leading-tight break-words">{details.title}</div>
            </div>
            <Separator />
        </div>
    )
}

/**
 * Resolve the data-management URL for an entry. Mirrors the legacy
 * `definitionPopoverLogic.viewFullDetailUrl` selector — Action / Event /
 * Property / Cohort each have their own page; everything else returns
 * `undefined` so the link is hidden.
 */
function resolveViewUrl(entry: MenuFilterEntry): string | undefined {
    const { group, item } = entry
    switch (group.type) {
        case TaxonomicFilterGroupType.Actions: {
            const id = (item as ActionType).id
            return id != null ? urls.action(id) : undefined
        }
        case TaxonomicFilterGroupType.Events:
        case TaxonomicFilterGroupType.CustomEvents: {
            const id = (item as EventDefinition).id
            return id ? urls.eventDefinition(id) : undefined
        }
        case TaxonomicFilterGroupType.EventProperties:
        case TaxonomicFilterGroupType.PersonProperties:
        case TaxonomicFilterGroupType.SessionProperties:
        case TaxonomicFilterGroupType.EventMetadata:
        case TaxonomicFilterGroupType.EventFeatureFlags: {
            const id = (item as PropertyDefinition).id
            return id ? urls.propertyDefinition(id) : undefined
        }
        case TaxonomicFilterGroupType.Cohorts:
        case TaxonomicFilterGroupType.CohortsWithAllUsers: {
            const id = (item as CohortType).id
            return id != null ? urls.cohort(id) : undefined
        }
        default:
            return undefined
    }
}
