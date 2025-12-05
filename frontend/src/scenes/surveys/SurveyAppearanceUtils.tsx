import clsx from 'clsx'
import { useValues } from 'kea'
import { useMemo, useRef } from 'react'
import { PrismAsyncLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup'

import { LemonBanner, LemonTabs, LemonTextArea } from '@posthog/lemon-ui'

import { darkTheme, lightTheme } from 'lib/components/CodeSnippet/theme'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { SurveyQuestionDescriptionContentType } from '~/types'

SyntaxHighlighter.registerLanguage('markup', markup)

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

    const PreTag = useMemo(
        () =>
            function PreTagComponent({
                children,
                ...props
            }: React.HTMLAttributes<HTMLPreElement> & { children: React.ReactNode }): JSX.Element {
                return (
                    <pre
                        {...props}
                        ref={preRef}
                        className="m-0 overflow-auto pointer-events-none h-full"
                        style={{
                            ...props.style,
                            fontFamily: 'inherit',
                            fontSize: 'inherit',
                            lineHeight: '1.5',
                        }}
                    >
                        {children}
                    </pre>
                )
            },
        []
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
                <SyntaxHighlighter
                    language="markup"
                    style={isDarkModeOn ? darkTheme : lightTheme}
                    customStyle={{
                        margin: 0,
                        padding: '10px 12px',
                        background: 'transparent',
                        height: '100%',
                        overflow: 'auto',
                        whiteSpace: 'pre-wrap',
                        wordWrap: 'break-word',
                        border: 'none',
                    }}
                    codeTagProps={{
                        style: {
                            fontFamily: CODE_FONT_FAMILY,
                            fontSize: 'inherit',
                            lineHeight: '1.5',
                        },
                    }}
                    PreTag={PreTag}
                >
                    {displayValue}
                </SyntaxHighlighter>
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
}: {
    value?: string
    onChange: (value: any) => void
    onTabChange: (key: SurveyQuestionDescriptionContentType) => void
    activeTab: SurveyQuestionDescriptionContentType
    textPlaceholder?: string
}): JSX.Element {
    return (
        <>
            <LemonTabs
                activeKey={activeTab}
                onChange={onTabChange}
                tabs={[
                    {
                        key: 'text',
                        label: <span className="text-sm">Text</span>,
                        content: (
                            <LemonTextArea
                                minRows={2}
                                value={value}
                                onChange={(v) => onChange(v)}
                                placeholder={textPlaceholder}
                            />
                        ),
                    },
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
