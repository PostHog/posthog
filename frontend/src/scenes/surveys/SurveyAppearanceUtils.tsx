import { IconLock } from '@posthog/icons'
import { LemonBanner, LemonTabs, LemonTextArea } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { CodeEditor } from 'lib/monaco/CodeEditor'

import { AvailableFeature, SurveyQuestionDescriptionContentType } from '~/types'

import { surveysLogic } from './surveysLogic'

export function PresentationTypeCard({
    title,
    description,
    children,
    onClick,
    value,
    active,
}: {
    title: string
    description?: string
    children: React.ReactNode
    onClick: () => void
    value: any
    active: boolean
}): JSX.Element {
    return (
        <div
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: 180, width: 200 }}
            className={clsx(
                'border rounded relative px-4 py-2 overflow-hidden',
                active ? 'border-primary' : 'border-border'
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
    const { surveysHTMLAvailable } = useValues(surveysLogic)

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
                                {!surveysHTMLAvailable && <IconLock className="ml-2" />}
                            </div>
                        ),
                        content: (
                            <div>
                                {surveysHTMLAvailable ? (
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
                                ) : (
                                    <PayGateMini feature={AvailableFeature.SURVEYS_TEXT_HTML}>
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
                                    </PayGateMini>
                                )}
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
