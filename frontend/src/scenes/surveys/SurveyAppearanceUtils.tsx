import clsx from 'clsx'
import { toHtml } from 'hast-util-to-html'
import xml from 'highlight.js/lib/languages/xml'
import { useValues } from 'kea'
import { common, createLowlight } from 'lowlight'
import { useEffect, useMemo, useRef, useState } from 'react'

import { LemonBanner, LemonTabs, LemonTextArea } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { SurveyQuestionDescriptionContentType } from '~/types'

import { htmlToPlainText, isRichTextCompatibleHtml, plainTextToHtml } from './surveyRichText'
import { SurveyRichTextEditor } from './SurveyRichTextEditor'

type HTMLEditorTab = SurveyQuestionDescriptionContentType | 'rich'

const lowlight = createLowlight(common)
lowlight.register({ xml })

const CODE_FONT_FAMILY = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace'

function HighlightedTextArea({
    value,
    onChange,
    placeholder,
}: {
    value?: string
    onChange: (value: string) => void
    placeholder?: string
}): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const textareaRef = useRef<HTMLTextAreaElement>(null)
    const preRef = useRef<HTMLPreElement>(null)

    const handleScroll = (): void => {
        if (textareaRef.current && preRef.current) {
            preRef.current.scrollTop = textareaRef.current.scrollTop
            preRef.current.scrollLeft = textareaRef.current.scrollLeft
        }
    }

    const displayValue = value || ''
    const showPlaceholder = !displayValue && placeholder
    const highlighted = useMemo(
        () =>
            lowlight.registered('xml') ? lowlight.highlight('xml', displayValue) : lowlight.highlightAuto(displayValue),
        [displayValue]
    )

    return (
        <div
            className={clsx(
                'relative font-mono text-[13px] border rounded overflow-hidden resize-y',
                isDarkModeOn ? 'bg-[#1e1e1e]' : 'bg-[#f5f5f5]'
            )}
            style={{ minHeight: '150px', height: '150px' }}
        >
            {showPlaceholder ? (
                <div
                    className="absolute inset-0 p-[10px_12px] text-muted pointer-events-none"
                    style={{ fontFamily: CODE_FONT_FAMILY, lineHeight: '1.5' }}
                >
                    {placeholder}
                </div>
            ) : (
                <pre
                    ref={preRef}
                    className={clsx(
                        'm-0 overflow-auto pointer-events-none bg-transparent h-full whitespace-pre-wrap',
                        'border-none leading-6'
                    )}
                    style={{
                        padding: '10px 12px',
                        wordWrap: 'break-word',
                        fontFamily: 'inherit',
                        fontSize: 'inherit',
                    }}
                >
                    <code
                        className={clsx('hljs leading-6', isDarkModeOn && 'hljs-dark')}
                        style={{
                            fontFamily: CODE_FONT_FAMILY,
                            fontSize: 'inherit',
                        }}
                        dangerouslySetInnerHTML={{ __html: toHtml(highlighted) }}
                    />
                </pre>
            )}
            <textarea
                ref={textareaRef}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                onScroll={handleScroll}
                aria-label="HTML code editor"
                spellCheck={false}
                autoCorrect="off"
                autoCapitalize="off"
                className={clsx(
                    'absolute inset-0 w-full h-full resize-none bg-transparent',
                    'p-[10px_12px] text-transparent selection:bg-primary-highlight',
                    'focus:outline-none focus:ring-1 focus:ring-primary',
                    isDarkModeOn ? 'caret-white' : 'caret-black'
                )}
                style={{
                    fontFamily: CODE_FONT_FAMILY,
                    fontSize: 'inherit',
                    lineHeight: '1.5',
                }}
            />
        </div>
    )
}

export function PresentationTypeCard({
    title,
    description,
    children,
    onClick,
    value,
    active,
    disabled,
}: {
    title: string
    description?: string
    children?: React.ReactNode
    onClick: () => void
    value: any
    active: boolean
    disabled?: boolean
}): JSX.Element {
    return (
        <div
            className={clsx(
                'border rounded relative px-4 py-2 overflow-hidden h-[180px] w-full',
                active ? 'border-accent' : 'border-primary',
                disabled && 'opacity-50'
            )}
        >
            <p className="font-semibold m-0">{title}</p>
            {description && <p className="m-0 text-xs">{description}</p>}
            <div className="relative mt-2 presentation-preview">{children}</div>
            <input
                onClick={onClick}
                className="opacity-0 absolute inset-0 h-full w-full cursor-pointer"
                name="type"
                value={value}
                type="radio"
                disabled={disabled}
            />
        </div>
    )
}

export function HTMLEditor({
    value,
    onChange,
    onTabChange,
    activeTab,
    textPlaceholder,
    textMinRows = 2,
    disableTabSwitching = false,
    className,
}: {
    value?: string
    onChange: (value: any) => void
    onTabChange: (key: SurveyQuestionDescriptionContentType) => void
    activeTab: SurveyQuestionDescriptionContentType
    textPlaceholder?: string
    textMinRows?: number
    disableTabSwitching?: boolean
    className?: string
}): JSX.Element {
    const richTextEnabled = useFeatureFlag('SURVEYS_RICH_TEXT_DESCRIPTIONS')
    const [htmlTab, setHtmlTab] = useState<'rich' | 'html' | null>(null)
    const [pendingConversion, setPendingConversion] = useState<'toHtml' | 'toText' | null>(null)
    const richTextCompatible = useMemo(() => isRichTextCompatibleHtml(value ?? ''), [value])
    const defaultHtmlTab = richTextCompatible ? 'rich' : 'html'
    const shownTab: HTMLEditorTab =
        activeTab === 'text' ? 'text' : richTextEnabled ? (htmlTab ?? defaultHtmlTab) : 'html'

    // Pick the tab once, so that an edit in the HTML tab does not move the author to the rich text tab
    useEffect(() => {
        if (activeTab === 'html' && htmlTab === null) {
            setHtmlTab(defaultHtmlTab)
        }
    }, [activeTab, htmlTab, defaultHtmlTab])

    // Convert the value once the parent has stored the new content type, so the two updates do not race
    useEffect(() => {
        const targetTab = pendingConversion === 'toHtml' ? 'html' : 'text'
        if (!pendingConversion || activeTab !== targetTab) {
            return
        }
        setPendingConversion(null)
        if (value) {
            onChange(pendingConversion === 'toHtml' ? plainTextToHtml(value) : htmlToPlainText(value))
        }
    }, [pendingConversion, activeTab, value, onChange])

    const handleTabChange = (key: HTMLEditorTab): void => {
        if (key !== 'text') {
            setHtmlTab(key)
        }
        const nextContentType = key === 'text' ? 'text' : 'html'
        if (nextContentType !== activeTab) {
            setPendingConversion(key === 'rich' ? 'toHtml' : shownTab === 'rich' ? 'toText' : null)
            onTabChange(nextContentType)
        }
    }

    return (
        <>
            <LemonTabs
                activeKey={shownTab}
                onChange={disableTabSwitching ? undefined : handleTabChange}
                tabs={[
                    {
                        key: 'text',
                        label: <span className="text-sm">Text</span>,
                        content: (
                            <LemonTextArea
                                minRows={textMinRows}
                                value={pendingConversion === 'toText' ? htmlToPlainText(value ?? '') : value}
                                onChange={(v) => onChange(v)}
                                placeholder={textPlaceholder}
                                className={className}
                            />
                        ),
                    },
                    richTextEnabled
                        ? {
                              key: 'rich',
                              label: <span className="text-sm">Rich text</span>,
                              content: (
                                  <div className="flex flex-col gap-2">
                                      {!richTextCompatible && (
                                          <LemonBanner type="warning">
                                              This description has HTML that the rich text editor can't show. If you
                                              edit it here, that formatting is removed. Use the HTML tab to keep it.
                                          </LemonBanner>
                                      )}
                                      <SurveyRichTextEditor
                                          value={
                                              pendingConversion === 'toHtml'
                                                  ? plainTextToHtml(value ?? '')
                                                  : (value ?? '')
                                          }
                                          onChange={onChange}
                                      />
                                      <div className="text-xs text-secondary">
                                          Formatting shows in web surveys. Some mobile SDKs don't show formatted
                                          descriptions.
                                      </div>
                                  </div>
                              ),
                          }
                        : null,
                    {
                        key: 'html',
                        label: <span className="text-sm">HTML</span>,
                        content: (
                            <HighlightedTextArea value={value} onChange={onChange} placeholder={textPlaceholder} />
                        ),
                    },
                ]}
            />
            {value && value?.toLowerCase().includes('<script') && (
                <LemonBanner type="warning">
                    Scripts won't run in the survey popover and we'll remove these on save. Use the API question mode to
                    run your own scripts in surveys.
                </LemonBanner>
            )}
        </>
    )
}
