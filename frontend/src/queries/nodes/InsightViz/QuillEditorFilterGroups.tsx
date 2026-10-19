import posthog from 'posthog-js'
import { useState } from 'react'

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger, Text } from '@posthog/quill'

import { slugify } from 'lib/utils/strings'

import type { InsightEditorFilterGroup, InsightLogicProps } from '~/types'

import { QuillEditorFilterItems } from './QuillEditorFilterItems'
import { isEditorGroupExpandedByDefault } from './useEditorGroupExpansion'

export interface QuillEditorFilterGroupsProps {
    editorFilterGroups: InsightEditorFilterGroup[]
    insightProps: InsightLogicProps
    queryKind?: string
}

export function QuillEditorFilterGroups({
    editorFilterGroups,
    insightProps,
    queryKind,
}: QuillEditorFilterGroupsProps): JSX.Element {
    const [openByTitle, setOpenByTitle] = useState<Record<string, boolean>>({})

    const openTitles = editorFilterGroups
        .filter(
            ({ title, defaultExpanded, collapsedSummary }) =>
                openByTitle[title] ?? isEditorGroupExpandedByDefault(defaultExpanded, !!collapsedSummary)
        )
        .map(({ title }) => title)

    return (
        <Accordion multiple value={openTitles} data-quill>
            {editorFilterGroups.map(({ title, collapsedSummary, headerExtra, editorFilters }) => {
                const isOpen = openTitles.includes(title)
                return (
                    <AccordionItem
                        key={title}
                        value={title}
                        onOpenChange={(open) => {
                            setOpenByTitle((current) => ({ ...current, [title]: open }))
                            posthog.capture('editor panel section toggled', {
                                section: title,
                                action: open ? 'opened' : 'closed',
                                query_kind: queryKind,
                            })
                        }}
                    >
                        <AccordionTrigger data-attr={'editor-filter-group-collapse-' + slugify(title)}>
                            <span className="flex items-baseline gap-2 min-w-0">
                                <span className="shrink-0">{title}</span>
                                {!isOpen && collapsedSummary ? (
                                    <Text size="xs" variant="muted" render={<span />} className="truncate">
                                        {collapsedSummary}
                                    </Text>
                                ) : null}
                            </span>
                        </AccordionTrigger>
                        <AccordionContent className="flex flex-col gap-3 min-w-0">
                            {headerExtra ? (
                                <div data-not-quill className="flex">
                                    {headerExtra}
                                </div>
                            ) : null}
                            <QuillEditorFilterItems editorFilters={editorFilters} insightProps={insightProps} />
                        </AccordionContent>
                    </AccordionItem>
                )
            })}
        </Accordion>
    )
}
