import React, { Children, ReactNode, createContext, isValidElement, useContext, useMemo } from 'react'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

interface OnboardingComponents {
    Steps: React.ComponentType<{ children: ReactNode }>
    Step: React.ComponentType<{
        title: string
        subtitle?: string
        badge?: 'required' | 'optional'
        checkpoint?: boolean
        docsOnly?: boolean
        children: ReactNode
    }>
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
    snippets?: Record<string, React.ComponentType<any>>
}

const OnboardingContext = createContext<OnboardingComponents | null>(null)

function Steps({ children }: { children: ReactNode }): JSX.Element {
    const validSteps = Children.toArray(children).filter((child) => {
        if (!isValidElement(child)) {
            return false
        }
        return !child.props.docsOnly
    })

    const numberedSteps = validSteps.map((step, index) => {
        if (isValidElement(step)) {
            return React.cloneElement(step, { stepNumber: index + 1 } as any)
        }
        return step
    })

    return <div className="space-y-6">{numberedSteps}</div>
}

function Step({
    title,
    subtitle,
    badge,
    docsOnly,
    stepNumber,
    children,
}: {
    title: string
    subtitle?: string
    badge?: 'required' | 'optional'
    checkpoint?: boolean
    docsOnly?: boolean
    stepNumber?: number
    children: ReactNode
}): JSX.Element | null {
    if (docsOnly) {
        return null
    }

    const numberedTitle = stepNumber ? `${stepNumber}. ${title}` : title

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <h3 className="m-0">{numberedTitle}</h3>
                {badge && (
                    <LemonTag type={badge === 'required' ? 'default' : 'option'} className="text-xs">
                        {badge}
                    </LemonTag>
                )}
            </div>
            {subtitle && <p className="text-muted text-sm m-0">{subtitle}</p>}
            <div>{children}</div>
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
    const langMap: Record<string, Language> = {
        bash: Language.Bash,
        python: Language.Python,
        ts: Language.TypeScript,
        javascript: Language.JavaScript,
        js: Language.JavaScript,
        text: Language.Text,
    }

    // If blocks array is provided, use it
    const codeBlocks: CodeBlockItem[] = blocks
        ? blocks.map((block) => ({
              language: block.language,
              code: block.code,
              file: block.file,
          }))
        : // Otherwise, use single block props
          language && code
          ? [
                {
                    language,
                    code,
                    file,
                },
            ]
          : []

    // Hooks must be called unconditionally
    const [selectedFile, setSelectedFile] = React.useState<string | null>(null)
    const uniqueFiles = codeBlocks
        .map((block) => block.file || 'default')
        .filter((file, index, self) => self.indexOf(file) === index)

    React.useEffect(() => {
        if (!selectedFile && uniqueFiles.length > 0) {
            setSelectedFile(uniqueFiles[0])
        }
    }, [selectedFile, uniqueFiles])

    if (codeBlocks.length === 0) {
        return <></>
    }

    if (codeBlocks.length === 1) {
        const block = codeBlocks[0]
        return <CodeSnippet language={langMap[block.language] || Language.Text}>{block.code}</CodeSnippet>
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
            <CodeSnippet language={langMap[selectedBlock.language] || Language.Text}>{selectedBlock.code}</CodeSnippet>
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
        <LemonBanner type={bannerType} className="[&>*]:font-normal">
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
    return <LemonMarkdown>{content}</LemonMarkdown>
}

function Blockquote({ children }: { children: ReactNode }): JSX.Element {
    return (
        <LemonBanner type="info" className="[&>*]:font-normal">
            {children}
        </LemonBanner>
    )
}

export function OnboardingContentWrapper({
    children,
    snippets,
}: {
    children: ReactNode
    snippets?: Record<string, React.ComponentType<any>>
}): JSX.Element {
    const components = useMemo<OnboardingComponents>(
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
            snippets,
        }),
        [snippets]
    )

    return <OnboardingContext.Provider value={components}>{children}</OnboardingContext.Provider>
}

export function useMDXComponents(): OnboardingComponents {
    const context = useContext(OnboardingContext)
    if (!context) {
        throw new Error('useMDXComponents must be used within OnboardingContentWrapper')
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
