import { MDXProvider } from '@mdx-js/react'
import { useValues } from 'kea'
import { memo, useMemo, useRef, useState } from 'react'

import { LemonBanner, LemonButton, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, getLanguage } from 'lib/components/CodeSnippet'
import { Link } from 'lib/lemon-ui/Link/Link'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

function mapCalloutTypeToBannerType(calloutType: string): 'info' | 'warning' | 'error' {
    if (calloutType === 'warning' || calloutType === 'warn' || calloutType === 'action') {
        return 'warning'
    }
    if (calloutType === 'error' || calloutType === 'danger' || calloutType === 'caution') {
        return 'error'
    }
    return 'info'
}

export function TabComponent({ children }: { children: React.ReactNode }): JSX.Element {
    return <>{children}</>
}

function TabList({ children }: { children: React.ReactNode }): JSX.Element {
    return <>{children}</>
}

function TabPanels({ children }: { children: React.ReactNode }): JSX.Element {
    return <>{children}</>
}

function TabPanel({ children }: { children: React.ReactNode }): JSX.Element {
    return <>{children}</>
}

function TabGroup({ tabs, children }: { tabs?: string[]; children: React.ReactNode }): JSX.Element {
    const childrenArray = Array.isArray(children) ? children : [children]
    const listChild = childrenArray.find((child: any) => child?.type === TabList)
    const panelsChild = childrenArray.find((child: any) => child?.type === TabPanels)

    const tabLabels = tabs || []
    const listItems = listChild?.props?.children
        ? Array.isArray(listChild.props.children)
            ? listChild.props.children
            : [listChild.props.children]
        : []

    const panelItems = panelsChild?.props?.children
        ? Array.isArray(panelsChild.props.children)
            ? panelsChild.props.children
            : [panelsChild.props.children]
        : []

    const tabItems = listItems.map((tab: any, index: number) => {
        const children = tab?.props?.children
        const label = typeof children === 'string' ? children : tabLabels[index] || `Tab ${index + 1}`
        return {
            key: String(index),
            label: label,
        }
    })

    const [activeTab, setActiveTab] = useState(tabItems[0]?.key || '0')
    const activePanel = panelItems[parseInt(activeTab)]
    const activePanelContent = activePanel?.type === TabPanel ? activePanel.props.children : activePanel

    return (
        <div className="mt-4 mb-4">
            <LemonTabs
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as string)}
                tabs={tabItems}
                className="mb-4"
            />
            {activePanelContent}
        </div>
    )
}

export const Tab = Object.assign(TabComponent, {
    Group: TabGroup,
    List: TabList,
    Panels: TabPanels,
    Panel: TabPanel,
})

interface MDXContainerProps {
    children: React.ReactNode
    className?: string
}

function MDXContainer({ children, className }: MDXContainerProps): JSX.Element {
    return <div className={className}>{children}</div>
}

export interface MDXProps {
    content: React.ComponentType<any>
    className?: string
}

const MDXRenderer = memo(function MDXRenderer({ content }: MDXProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const apiToken = currentTeam?.api_token
    const stepIndexRef = useRef(0)

    const components = useMemo(() => {
        stepIndexRef.current = 0
        return {
            Steps: ({ children }: { children: React.ReactNode }) => <>{children}</>,
            Step: ({
                title,
                badge,
                checkpoint,
                docsOnly,
                children,
            }: {
                title: string
                badge?: string
                checkpoint?: boolean
                docsOnly?: boolean
                children: React.ReactNode
            }) => {
                if (docsOnly) {
                    return null
                }

                stepIndexRef.current++

                const displayBadge = checkpoint ? 'checkpoint' : badge

                return (
                    <div key={stepIndexRef.current} className="mb-8">
                        <div className="flex items-center gap-2 mb-2">
                            <h2 className="m-0">
                                Step {stepIndexRef.current}: {title}
                            </h2>
                            {displayBadge && (
                                <LemonTag
                                    type={
                                        displayBadge === 'required'
                                            ? 'highlight'
                                            : displayBadge === 'checkpoint'
                                              ? 'success'
                                              : 'default'
                                    }
                                >
                                    {displayBadge}
                                </LemonTag>
                            )}
                        </div>
                        <div className="deprecated-space-y-4">{children}</div>
                    </div>
                )
            },
            MultiLanguage: ({ children }: { children: React.ReactNode }) => {
                const childrenArray = Array.isArray(children) ? children : [children]
                const languageData = childrenArray
                    .filter((element) => element && typeof element === 'object' && 'props' in element)
                    .map((element: any) => {
                        const codeElement = element.props?.children
                        const file = element.props?.file
                        const className = codeElement?.props?.className || ''
                        const language = className.replace('language-', '')

                        return {
                            file: file,
                            language: language,
                            element: element,
                        }
                    })
                    .filter((item) => item.language)

                const [selectedKey, setSelectedKey] = useState(languageData[0]?.file || languageData[0]?.language || '')

                if (languageData.length === 0) {
                    return <>{children}</>
                }

                const selectedElement = languageData.find(
                    (item) => (item.file || item.language) === selectedKey
                )?.element

                return (
                    <>
                        {languageData.length > 1 && (
                            <div className="mb-2 [&_ul]:list-none">
                                <LemonTabs
                                    activeKey={selectedKey}
                                    onChange={(key) => setSelectedKey(key)}
                                    tabs={languageData.map((item) => ({
                                        key: item.file || item.language,
                                        label:
                                            item.file || item.language.charAt(0).toUpperCase() + item.language.slice(1),
                                    }))}
                                />
                            </div>
                        )}
                        {selectedElement || (languageData.length === 1 && childrenArray[0])}
                    </>
                )
            },
            pre: (props: any) => {
                return <pre {...props} />
            },
            code: ({ className, children, ...props }: any) => {
                if (className && className.startsWith('language-')) {
                    const language = className.replace('language-', '') || 'text'
                    const codeContent = String(children)
                        .trim()
                        .replace('<ph_project_api_key>', apiToken || '<ph_project_api_key>')
                        .replace('<ph_client_api_host>', apiHostOrigin())

                    const codeSnippetLanguage = getLanguage(language)

                    return (
                        <CodeSnippet language={codeSnippetLanguage} compact>
                            {codeContent}
                        </CodeSnippet>
                    )
                }
                return <code {...props}>{children}</code>
            },
            p: (props: any) => <p {...props} />,
            h1: (props: any) => <h1 {...props} />,
            h2: (props: any) => <h2 {...props} />,
            h3: (props: any) => <h3 {...props} />,
            h4: (props: any) => <h4 {...props} />,
            ul: (props: any) => <ul className="pl-6 list-disc" {...props} />,
            ol: (props: any) => <ol className="pl-6 list-decimal" {...props} />,
            li: (props: any) => <li {...props} />,
            blockquote: ({ children, ...props }: any) => (
                <LemonBanner type="info" className="mt-2 [&>*]:font-normal" {...props}>
                    {children}
                </LemonBanner>
            ),
            a: ({ href, children, ...props }: any) => (
                <Link to={href} target="_blank" targetBlankIcon {...props}>
                    {children}
                </Link>
            ),
            CalloutBox: ({ type, title, children }: { type?: string; title?: string; children: React.ReactNode }) => {
                const calloutType = type || 'info'
                const bannerType = mapCalloutTypeToBannerType(calloutType)

                return (
                    <LemonBanner type={bannerType} className="mt-2 [&>*]:font-normal">
                        {title && <h3 className="mb-2">{title}</h3>}
                        {children}
                    </LemonBanner>
                )
            },
            OSButton: ({
                variant,
                size,
                to,
                external,
                children,
                className,
            }: {
                variant?: string
                size?: string
                to?: string
                external?: boolean
                children: React.ReactNode
                className?: string
            }) => {
                const buttonType = variant === 'secondary' ? 'secondary' : 'primary'
                const buttonSize = size === 'sm' ? 'small' : size === 'lg' ? 'large' : undefined

                return (
                    <LemonButton
                        to={to}
                        targetBlank={external}
                        type={buttonType}
                        size={buttonSize}
                        className={className}
                    >
                        {children}
                    </LemonButton>
                )
            },
            ProductScreenshot: ({
                imageLight,
                imageDark,
                alt,
                caption,
            }: {
                imageLight?: string
                imageDark?: string
                alt?: string
                caption?: string
            }) => {
                const imageSrc = isDarkModeOn && imageDark ? imageDark : imageLight
                return (
                    <div className="mt-4 mb-4">
                        {imageSrc && <img src={imageSrc} alt={alt || ''} className="w-full rounded border" />}
                        {caption && <p className="text-muted text-sm mt-2">{caption}</p>}
                    </div>
                )
            },
            Tab: Tab,
        }
    }, [apiToken, isDarkModeOn])

    const MDXComponent = content as React.ComponentType<{ components?: any }>
    return (
        <MDXProvider components={components}>
            <MDXComponent components={components} />
        </MDXProvider>
    )
})

function MDXComponent({ content, className }: MDXProps): JSX.Element {
    return (
        <MDXContainer className={className}>
            <MDXRenderer content={content} />
        </MDXContainer>
    )
}

export const MDX = Object.assign(MDXComponent, {
    Container: MDXContainer,
    Renderer: MDXRenderer,
})
