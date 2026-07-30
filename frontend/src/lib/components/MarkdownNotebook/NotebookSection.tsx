import clsx from 'clsx'
import { KeyboardEvent as ReactKeyboardEvent, useRef, useState } from 'react'

import { IconChevronRight, IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MarkdownNotebookSection, getMarkdownNotebookSectionMemberCount } from './documentModel'
import { wasNotebookNodeJustInserted } from './freshlyInserted'
import { NotebookMode } from './types'

const TITLE_PLACEHOLDER = 'Add a title'
const UNTITLED_LABEL = 'Untitled section'

export function NotebookSectionHeader({
    section,
    mode,
    toggleSection,
    setSectionTitle,
    removeSection,
}: {
    section: MarkdownNotebookSection
    mode: NotebookMode
    toggleSection: (sectionNodeId: string) => void
    setSectionTitle: (sectionNodeId: string, title: string) => void
    removeSection: (sectionNodeId: string) => void
}): JSX.Element {
    const sectionNodeId = section.node.id
    // Escape blurs the input, which fires the commit synchronously before the draft state update
    // lands — this ref lets the commit see the cancel intent in that same tick.
    const cancellingRef = useRef(false)
    const [titleDraft, setTitleDraft] = useState<string | null>(null)
    const memberCount = getMarkdownNotebookSectionMemberCount(section)

    const commitTitle = (): void => {
        const draft = titleDraft
        setTitleDraft(null)
        if (cancellingRef.current) {
            cancellingRef.current = false
            return
        }
        if (draft !== null && draft.trim() !== section.title) {
            setSectionTitle(sectionNodeId, draft.trim())
        }
    }

    const handleTitleKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>): void => {
        if (event.key === 'Enter') {
            event.preventDefault()
            event.currentTarget.blur()
            return
        }
        if (event.key === 'Escape') {
            event.preventDefault()
            cancellingRef.current = true
            event.currentTarget.blur()
        }
    }

    return (
        <div className="MarkdownNotebook__section-header" contentEditable={false}>
            <button
                type="button"
                className="MarkdownNotebook__section-toggle"
                aria-expanded={!section.collapsed}
                aria-label={section.collapsed ? 'Expand section' : 'Collapse section'}
                data-attr="markdown-notebook-section-toggle"
                onClick={() => toggleSection(sectionNodeId)}
            >
                <IconChevronRight
                    className={clsx(
                        'MarkdownNotebook__section-chevron',
                        !section.collapsed && 'MarkdownNotebook__section-chevron--open'
                    )}
                />
            </button>
            {mode === 'edit' ? (
                <input
                    className="MarkdownNotebook__section-title MarkdownNotebook__section-title--input"
                    value={titleDraft ?? section.title}
                    placeholder={TITLE_PLACEHOLDER}
                    aria-label="Section title"
                    spellCheck={false}
                    autoFocus={wasNotebookNodeJustInserted(sectionNodeId)}
                    onChange={(event) => setTitleDraft(event.target.value)}
                    onBlur={commitTitle}
                    onKeyDown={handleTitleKeyDown}
                />
            ) : (
                <div className={clsx('MarkdownNotebook__section-title', !section.title && 'text-secondary')}>
                    {section.title || UNTITLED_LABEL}
                </div>
            )}
            {section.collapsed ? (
                <span className="MarkdownNotebook__section-count">
                    {memberCount === 1 ? '1 block hidden' : `${memberCount} blocks hidden`}
                </span>
            ) : null}
            {mode === 'edit' ? (
                <LemonButton
                    size="xsmall"
                    icon={<IconTrash />}
                    tooltip="Ungroup section, keeping its blocks"
                    aria-label="Ungroup section"
                    data-attr="markdown-notebook-section-remove"
                    onClick={() => removeSection(sectionNodeId)}
                />
            ) : null}
        </div>
    )
}
