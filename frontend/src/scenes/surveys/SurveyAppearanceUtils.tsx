import { IconLock } from '@posthog/icons'
import { LemonBanner, LemonTabs, LemonTextArea } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CodeEditor } from 'lib/components/CodeEditors'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { AvailableFeature, SurveyQuestionDescriptionContentType } from '~/types'

import { surveyLogic } from './surveyLogic'
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
    initialActiveTab,
    textPlaceholder,
}: {
    value?: string
    onChange: (value: any) => void
    onTabChange: (key: SurveyQuestionDescriptionContentType) => void
    initialActiveTab: SurveyQuestionDescriptionContentType | undefined
    textPlaceholder?: string
}): JSX.Element {
    const { surveysHTMLAvailable } = useValues(surveysLogic)
    const { activeTabKey } = useValues(surveyLogic)
    const { setActiveTab } = useActions(surveyLogic)

    // Initialize the tab state; useful for when user opens the editor for the first time,
    // or for when they're editing an existing survey question.
    if (activeTabKey !== initialActiveTab) {
        setActiveTab(initialActiveTab ?? 'text')
    }

    const handleTabChange = (key: SurveyQuestionDescriptionContentType): void => {
        setActiveTab(key)
        onTabChange(key)
    }

    return (
        <>
            <LemonTabs
                activeKey={activeTabKey as SurveyQuestionDescriptionContentType}
                onChange={handleTabChange}
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
