import clsx from 'clsx'

import { LemonBanner, LemonTabs, LemonTextArea } from '@posthog/lemon-ui'

import { CodeEditor } from 'lib/monaco/CodeEditor'

import { SurveyQuestionDescriptionContentType } from '~/types'

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
                        label: (
                            <div>
                                <span className="text-sm">HTML</span>
                            </div>
                        ),
                        content: (
                            <div>
                                <CodeEditor
                                    className="border"
                                    language="html"
                                    value={value}
                                    onChange={(v) => onChange(v ?? '')}
                                    height={150}
                                    options={{
                                        minimap: {
                                            enabled: false,
                                        },
                                        scrollbar: {
                                            alwaysConsumeMouseWheel: false,
                                        },
                                        wordWrap: 'on',
                                        scrollBeyondLastLine: false,
                                        automaticLayout: true,
                                        fixedOverflowWidgets: true,
                                        lineNumbers: 'off',
                                        glyphMargin: false,
                                        folding: false,
                                    }}
                                />
                            </div>
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
