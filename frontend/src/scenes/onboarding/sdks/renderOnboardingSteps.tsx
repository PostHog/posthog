import { useState } from 'react'

import { LemonBanner, LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { getLanguage } from 'lib/components/CodeSnippet/CodeSnippet'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { apiHostOrigin } from 'lib/utils/apiHost'

type SDKLanguage = string

export interface CodeBlock {
    content: string
    label: string
    language: string
    tab: string
}

export interface MultiCodeItem {
    type: 'multi_code'
    languages: string[]
    code_blocks: CodeBlock[]
}

export interface MarkdownItem {
    type: 'markdown'
    content: string
}

export interface CodeItem {
    type: 'code'
    content: string
    language: string
    label?: string
}

export interface NoteItem {
    type: 'note'
    content: string
}

export interface NotesItem {
    type: 'notes'
    content: string
}

export interface CalloutItem {
    type: 'callout'
    content: string
    callout_type?: string
    title?: string
}

export interface TableItem {
    type: 'table'
    headers: string[]
    rows: string[][]
}

export interface ScreenshotItem {
    type: 'screenshot'
    alt?: string
    caption?: string
    imageLight?: string
    imageDark?: string
}

export interface ButtonItem {
    type: 'button'
    url: string
    text: string
    variant?: string
    external?: boolean
    app?: Array<{ type: string; event?: string; message?: string }>
}

export interface SectionHeaderItem {
    type: 'section_header'
    text: string
}

export interface TabItem {
    id: string
    label: string
    content: ContentItem[]
}

export interface TabbedItem {
    type: 'tabbed'
    tabs: TabItem[]
}

export type ContentItem =
    | MarkdownItem
    | MultiCodeItem
    | CodeItem
    | NoteItem
    | NotesItem
    | CalloutItem
    | TableItem
    | ScreenshotItem
    | ButtonItem
    | SectionHeaderItem
    | TabbedItem

export function renderMarkdown(item: MarkdownItem, index: number): JSX.Element {
    return (
        <div key={index}>
            <LemonMarkdown>{item.content}</LemonMarkdown>
        </div>
    )
}

function MultiCodeSnippet({
    item,
    index,
    apiToken,
}: {
    item: MultiCodeItem
    index: number
    apiToken: string | null | undefined
}): JSX.Element {
    const codeBlocks = item.code_blocks
    const languages = item.languages

    const availableLanguages = codeBlocks.map((block) => {
        const languageKey = block.tab || block.label.toLowerCase()
        return { label: block.label, key: languageKey, block }
    })

    const defaultLanguage = (languages[0] || availableLanguages[0]?.key) as SDKLanguage
    const [selectedLanguage, setSelectedLanguage] = useState<SDKLanguage>(defaultLanguage)

    const selectedBlock = availableLanguages.find((lang) => lang.key === selectedLanguage)?.block || codeBlocks[0]
    const codeContent = selectedBlock.content
        .replace('<ph_project_api_key>', apiToken || '<ph_project_api_key>')
        .replace('<ph_client_api_host>', apiHostOrigin())

    return (
        <div key={index}>
            {availableLanguages.length > 1 && (
                <LemonTabs
                    activeKey={selectedLanguage}
                    onChange={(key) => setSelectedLanguage(key as SDKLanguage)}
                    tabs={availableLanguages.map((lang) => ({ key: lang.key, label: lang.label }))}
                    className="mb-2"
                />
            )}
            <CodeSnippet language={getLanguage(selectedBlock.language)}>{codeContent}</CodeSnippet>
        </div>
    )
}

export function renderMultiCode(item: MultiCodeItem, index: number, apiToken: string | null | undefined): JSX.Element {
    return <MultiCodeSnippet item={item} index={index} apiToken={apiToken} />
}

export function renderCode(item: CodeItem, index: number, apiToken: string | null | undefined): JSX.Element {
    const codeContent = item.content
        .replace('<ph_project_api_key>', apiToken || '<ph_project_api_key>')
        .replace('<ph_client_api_host>', apiHostOrigin())

    return (
        <div key={index}>
            <CodeSnippet language={getLanguage(item.language)}>{codeContent}</CodeSnippet>
        </div>
    )
}

export function renderNote(item: NoteItem, index: number): JSX.Element {
    return (
        <LemonBanner key={index} type="info" className="mt-2">
            <LemonMarkdown>{item.content}</LemonMarkdown>
        </LemonBanner>
    )
}

export function renderNotes(item: NotesItem, index: number): JSX.Element {
    return (
        <LemonBanner key={index} type="info" className="mt-2">
            <LemonMarkdown>{item.content}</LemonMarkdown>
        </LemonBanner>
    )
}

export function renderCallout(item: CalloutItem, index: number): JSX.Element {
    const calloutType = item.callout_type || 'info'
    const bannerType = calloutType === 'warning' ? 'warning' : calloutType === 'error' ? 'error' : 'info'
    const title = item.title

    return (
        <LemonBanner key={index} type={bannerType} className="mt-2">
            {title && <h4 className="mb-2">{title}</h4>}
            <LemonMarkdown>{item.content}</LemonMarkdown>
        </LemonBanner>
    )
}

export function renderTable(item: TableItem, index: number): JSX.Element {
    return (
        <div key={index} className="mt-4 mb-4">
            <table className="w-full border-collapse">
                <thead>
                    <tr>
                        {item.headers.map((header, hIndex) => (
                            <th key={hIndex} className="border border-border p-2 text-left bg-bg-light">
                                <LemonMarkdown>{header}</LemonMarkdown>
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {item.rows.map((row, rIndex) => (
                        <tr key={rIndex}>
                            {row.map((cell, cIndex) => (
                                <td key={cIndex} className="border border-border p-2">
                                    <LemonMarkdown>{cell}</LemonMarkdown>
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

export function renderScreenshot(item: ScreenshotItem, index: number, isDarkModeOn: boolean): JSX.Element {
    const alt = item.alt || ''
    const caption = item.caption
    const imageSrc = isDarkModeOn && item.imageDark ? item.imageDark : item.imageLight

    return (
        <div key={index} className="mt-4 mb-4">
            {imageSrc && <img src={imageSrc} alt={alt} className="w-full rounded border" />}
            {caption && <p className="text-muted text-sm mt-2">{caption}</p>}
        </div>
    )
}

export function renderButton(item: ButtonItem, index: number): JSX.Element {
    const variant = item.variant || 'primary'
    const external = item.external || false

    if (item.app && Array.isArray(item.app)) {
        const liveCheck = item.app.find((a) => a.type === 'live_check')
        if (liveCheck && 'event' in liveCheck) {
            return (
                <div key={index} className="mt-4 mb-4">
                    <LemonButton
                        to={item.url}
                        targetBlank={external}
                        type={variant === 'secondary' ? 'secondary' : 'primary'}
                    >
                        {item.text}
                    </LemonButton>
                    {liveCheck.message && <p className="text-muted text-sm mt-2">{liveCheck.message}</p>}
                </div>
            )
        }
    }

    return (
        <div key={index} className="mt-4 mb-4">
            <LemonButton to={item.url} targetBlank={external} type={variant === 'secondary' ? 'secondary' : 'primary'}>
                {item.text}
            </LemonButton>
        </div>
    )
}

export function renderSectionHeader(item: SectionHeaderItem, index: number): JSX.Element {
    return (
        <h4 key={index} className="mt-6 mb-3 font-semibold">
            {item.text}
        </h4>
    )
}

function TabbedContent({
    item,
    index,
    apiToken,
    isDarkModeOn,
}: {
    item: TabbedItem
    index: number
    apiToken: string | null | undefined
    isDarkModeOn: boolean
}): JSX.Element {
    const [activeTab, setActiveTab] = useState<string>(item.tabs[0]?.id || '')

    const activeTabContent = item.tabs.find((tab) => tab.id === activeTab)

    return (
        <div key={index} className="mt-4 mb-4">
            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as string)}
                tabs={item.tabs.map((tab) => ({ key: tab.id, label: tab.label }))}
                className="mb-4"
            />
            {activeTabContent && (
                <div className="deprecated-space-y-4">
                    {activeTabContent.content
                        .map((contentItem, itemIndex) =>
                            renderContentItem(contentItem as any, itemIndex, apiToken, isDarkModeOn)
                        )
                        .filter(Boolean)}
                </div>
            )}
        </div>
    )
}

export function renderTabbed(
    item: TabbedItem,
    index: number,
    apiToken: string | null | undefined,
    isDarkModeOn: boolean
): JSX.Element {
    return <TabbedContent item={item} index={index} apiToken={apiToken} isDarkModeOn={isDarkModeOn} />
}

export function renderContentItem(
    item: ContentItem,
    index: number,
    apiToken: string | null | undefined,
    isDarkModeOn: boolean
): JSX.Element | null {
    switch (item.type) {
        case 'markdown':
            return renderMarkdown(item, index)
        case 'multi_code':
            return renderMultiCode(item, index, apiToken)
        case 'code':
            return renderCode(item, index, apiToken)
        case 'note':
            return renderNote(item, index)
        case 'notes':
            return renderNotes(item, index)
        case 'callout':
            return renderCallout(item, index)
        case 'table':
            return renderTable(item, index)
        case 'screenshot':
            return renderScreenshot(item, index, isDarkModeOn)
        case 'button':
            return renderButton(item, index)
        case 'section_header':
            return renderSectionHeader(item, index)
        case 'tabbed':
            return renderTabbed(item, index, apiToken, isDarkModeOn)
        default:
            return null
    }
}
