import { useValues } from 'kea'
import React, { Children, ReactNode, createContext, isValidElement, useContext, useMemo } from 'react'

import { StepProps, StepsProps } from '@posthog/shared-onboarding/steps'

import { CodeSnippet, getLanguage } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

interface OnboardingComponents {
    Steps: React.ComponentType<StepsProps>
    Step: React.ComponentType<StepProps>
    CodeBlock: React.ComponentType<{
        blocks?: Array<{ language: string; code: string; file?: string }>
        language?: string
        code?: string
        file?: string
    }>
    CalloutBox: React.ComponentType<{
        type: 'action' | 'fyi' | 'caution'
        icon?: string
        title?: string
        children: ReactNode
    }>
    ProductScreenshot: React.ComponentType<{
        imageLight: string
        imageDark: string
        alt: string
        classes?: string
        className?: string
        padding?: boolean
    }>
    OSButton: React.ComponentType<any>
    Markdown: React.ComponentType<{ children: string | ReactNode }>
    Blockquote: React.ComponentType<{ children: ReactNode }>
    dedent: (strings: TemplateStringsArray | string, ...values: any[]) => string
    Tab: {
        Group: React.ComponentType<{ tabs: string[]; children: ReactNode }>
        List: React.ComponentType<{ children: ReactNode }>
        Panels: React.ComponentType<{ children: ReactNode }>
        Panel: React.ComponentType<{ children: ReactNode }>
    } & React.ComponentType<{ children: ReactNode }>
    snippets?: Record<string, React.ComponentType<any>>
    selectedFile?: string | null
    setSelectedFile?: (file: string) => void
}

const OnboardingContext = createContext<OnboardingComponents | null>(null)

function Steps({ children }: StepsProps): JSX.Element {
    let stepNumber = 0

    const processedChildren = Children.map(children, (child) => {
        if (!isValidElement(child)) {
            return child
        }

        // Only number Step components - check if it's actually a Step component
        const isStep = child.type === Step && 'title' in child.props && typeof child.props.title === 'string'

        if (isStep && !child.props.docsOnly) {
            stepNumber += 1
            return React.cloneElement(child, { stepNumber } as any)
        }

        return child
    })

    return <div className="space-y-6">{processedChildren}</div>
}

function Step({
    title,
    subtitle,
    badge,
    docsOnly,
    stepNumber,
    children,
}: StepProps & { stepNumber?: number }): JSX.Element | null {
    if (docsOnly) {
        return null
    }

    const numberedTitle = stepNumber ? `${stepNumber}. ${title}` : title

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <h3 className="m-0">{numberedTitle}</h3>
                {badge && (
                    <LemonTag
                        type={badge === 'required' ? 'default' : badge === 'recommended' ? 'success' : 'option'}
                        className="text-xs"
                    >
                        {badge}
                    </LemonTag>
                )}
            </div>
            {subtitle && <p className="text-muted text-sm m-0">{subtitle}</p>}
            <div className="space-y-4">{children}</div>
        </div>
    )
}

interface CodeBlockItem {
    language: string
    code: string
    file?: string
}

function CodeBlock({
    blocks,
    language,
    code,
    file,
}: {
    blocks?: Array<{ language: string; code: string; file?: string }>
    language?: string
    code?: string
    file?: string
}): JSX.Element {
    const context = useContext(OnboardingContext)
    const globalSelectedFile = context?.selectedFile
    const globalSetSelectedFile = context?.setSelectedFile
    const { currentTeam } = useValues(teamLogic)
    const host = apiHostOrigin()

    const replacePlaceholders = (codeString: string): string => {
        return codeString
            .replace(/<ph_project_api_key>/g, currentTeam?.api_token ?? '<ph_project_api_key>')
            .replace(/<ph_client_api_host>/g, host)
            .replace(/<team_id>/g, currentTeam?.id?.toString() ?? '<team_id>')
    }

    // If blocks array is provided, use it
    const codeBlocks: CodeBlockItem[] = blocks
        ? blocks.map((block) => ({
              language: block.language,
              code: replacePlaceholders(block.code),
              file: block.file,
          }))
        : // Otherwise, use single block props
          language && code
          ? [
                {
                    language,
                    code: replacePlaceholders(code),
                    file,
                },
            ]
          : []

    const uniqueFiles = codeBlocks
        .map((block) => block.file || 'default')
        .filter((file, index, self) => self.indexOf(file) === index)

    // Use global selected file if available and it exists in this block's files
    const selectedFile =
        globalSelectedFile && uniqueFiles.includes(globalSelectedFile) ? globalSelectedFile : uniqueFiles[0] || null

    const setSelectedFile = (file: string): void => {
        if (globalSetSelectedFile) {
            globalSetSelectedFile(file)
        }
    }

    if (codeBlocks.length === 0) {
        return <></>
    }

    if (codeBlocks.length === 1) {
        const block = codeBlocks[0]
        return (
            <CodeSnippet className="my-4" language={getLanguage(block.language)}>
                {block.code}
            </CodeSnippet>
        )
    }

    // Multiple code blocks - use tabs
    const selectedBlock = codeBlocks.find((block) => (block.file || 'default') === selectedFile)

    if (!selectedBlock) {
        return <></>
    }

    return (
        <div className="space-y-2">
            {uniqueFiles.length > 1 && (
                <LemonTabs
                    activeKey={selectedFile || uniqueFiles[0]}
                    onChange={(key) => setSelectedFile(key as string)}
                    tabs={uniqueFiles.map((file) => ({
                        key: file,
                        label: file,
                    }))}
                />
            )}
            <CodeSnippet language={getLanguage(selectedBlock.language)}>{selectedBlock.code}</CodeSnippet>
        </div>
    )
}

function CalloutBox({
    type,
    title,
    children,
}: {
    type: 'action' | 'fyi' | 'caution'
    icon?: string
    title?: string
    children: ReactNode
}): JSX.Element {
    const bannerType = type === 'caution' ? 'warning' : type === 'action' ? 'info' : 'info'

    return (
        <LemonBanner type={bannerType} className="my-4 [&>*]:font-normal">
            {title && <strong>{title}</strong>}
            {children}
        </LemonBanner>
    )
}

function ProductScreenshot({
    imageLight,
    alt,
    classes,
    className,
    padding = true,
}: {
    imageLight: string
    imageDark?: string
    alt: string
    classes?: string
    className?: string
    padding?: boolean
}): JSX.Element {
    return (
        <div className={className}>
            <img src={imageLight} alt={alt} className={`${classes || ''} ${padding ? 'p-4' : ''}`} />
        </div>
    )
}

function OSButton(props: any): JSX.Element {
    return <LemonButton {...props} />
}

function Markdown({ children }: { children: string | ReactNode }): JSX.Element {
    const content = typeof children === 'string' ? children : String(children)

    return <LemonMarkdown disableDocsRedirect={true}>{content}</LemonMarkdown>
}

function Blockquote({ children }: { children: ReactNode }): JSX.Element {
    return (
        <LemonBanner type="info" className="my-4 [&>*]:font-normal">
            {children}
        </LemonBanner>
    )
}

const TabContext = createContext<{ activeTab: number; setActiveTab: (index: number) => void } | null>(null)

function TabGroup({ tabs, children }: { tabs: string[]; children: ReactNode }): JSX.Element {
    const [activeTab, setActiveTab] = React.useState(0)

    return (
        <TabContext.Provider value={{ activeTab, setActiveTab }}>
            <div>
                <LemonTabs
                    activeKey={String(activeTab)}
                    onChange={(key) => setActiveTab(Number(key))}
                    tabs={tabs.map((tab, idx) => ({ key: String(idx), label: tab }))}
                />
                {children}
            </div>
        </TabContext.Provider>
    )
}

function TabList(): JSX.Element {
    // Tab.List is not rendered, it's just for compatibility with Website tabs
    return <></>
}

function TabItem(): JSX.Element {
    // Individual Tab items are not rendered, it's just for compatibility with Website tabs
    return <></>
}

function TabPanels({ children }: { children: ReactNode }): JSX.Element {
    const context = useContext(TabContext)
    if (!context) {
        throw new Error('Tab.Panels must be used within Tab.Group')
    }
    const panels = Children.toArray(children)
    return <div className="mt-4">{panels[context.activeTab]}</div>
}

function TabPanel({ children }: { children: ReactNode }): JSX.Element {
    return <>{children}</>
}

const Tab = Object.assign(TabItem, {
    Group: TabGroup,
    List: TabList,
    Panels: TabPanels,
    Panel: TabPanel,
})

// This is a wrapper to share certain onboarding instructions with the main website repo.
export function OnboardingDocsContentWrapper({
    children,
    snippets,
    createSnippets,
}: {
    children: ReactNode
    snippets?: Record<string, React.ComponentType<any>>
    createSnippets?: (components: OnboardingComponents) => Record<string, React.ComponentType<any>>
}): JSX.Element {
    const [selectedFile, setSelectedFile] = React.useState<string | null>(null)

    const baseComponents = useMemo<Omit<OnboardingComponents, 'snippets'>>(
        () => ({
            Steps,
            Step,
            CodeBlock,
            CalloutBox,
            ProductScreenshot,
            OSButton,
            Markdown,
            Blockquote,
            dedent,
            Tab,
            selectedFile,
            setSelectedFile,
        }),
        [selectedFile]
    )

    const finalSnippets = useMemo(() => {
        if (createSnippets) {
            return createSnippets(baseComponents as OnboardingComponents)
        }
        return snippets
    }, [createSnippets, snippets, baseComponents])

    const components = useMemo<OnboardingComponents>(
        () =>
            ({
                ...baseComponents,
                snippets: finalSnippets,
            }) as OnboardingComponents,
        [baseComponents, finalSnippets]
    )

    return (
        <OnboardingContext.Provider value={components}>
            <div className="w-full">{children}</div>
        </OnboardingContext.Provider>
    )
}

export function useMDXComponents(): OnboardingComponents {
    const context = useContext(OnboardingContext)
    if (!context) {
        throw new Error('useMDXComponents must be used within OnboardingDocsContentWrapper')
    }
    return context
}

/**
 * Removes leading indentation from a template literal string.
 * Useful for formatting code blocks and markdown content in JSX.
 *
 * @param strings - Template literal strings
 * @param values - Interpolated values
 * @returns Dedented string
 */
export function dedent(strings: TemplateStringsArray | string, ...values: any[]): string {
    const str =
        typeof strings === 'string'
            ? strings
            : Array.isArray(strings)
              ? strings.reduce((acc, s, i) => acc + s + (values[i] || ''), '')
              : String(strings)
    const lines = str.split('\n')
    const firstNonEmptyLine = lines.find((line) => line.trim())
    if (!firstNonEmptyLine) {
        return str.trim()
    }
    const indent = firstNonEmptyLine.match(/^(\s*)/)?.[1]?.length || 0
    return lines
        .map((line) => (line.length >= indent ? line.slice(indent) : line))
        .join('\n')
        .trim()
}
