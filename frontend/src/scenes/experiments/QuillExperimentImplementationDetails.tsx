import { useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Heading,
    Select,
    SelectContent,
    SelectGroup,
    SelectGroupLabel,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
} from '@posthog/quill'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IconOpenInApp } from 'lib/lemon-ui/icons'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { Experiment, MultivariateFlagVariant, SDKKey } from '~/types'

import {
    PromptExperimentAgentPromptSnippet,
    PromptExperimentJSSnippet,
    PromptExperimentPythonSnippet,
} from './ExperimentCodeSnippets'
import {
    AGENT_PROMPT_HELP,
    type ImplementationSnippetPlacement,
    LibraryType,
    OPTIONS,
    type OnSnippetCopied,
    PROMPT_DOCS_URL,
    type PromptImplementationTab,
    PromptPayloadHelp,
    reportAgentPromptCopied,
    reportImplementationSnippetCopied,
} from './ExperimentImplementationDetails'
import { getExperimentVariants } from './utils'
import { WEB_IMPLEMENTATION_HELP, toolbarDomainDescription } from './WebExperimentImplementationDetails'

function DocsLink({ to, children }: { to: string; children: React.ReactNode }): JSX.Element {
    return (
        <Button
            variant="link-muted"
            size="sm"
            className="self-start px-0"
            nativeButton={false}
            render={<LinkPrimitive to={to} target="_blank" />}
        >
            {children}
        </Button>
    )
}

function QuillCodeLanguageSelect({
    selectedOptionValue,
    selectOption,
}: {
    selectedOptionValue: string
    selectOption: (selectedValue: string) => void
}): JSX.Element {
    const selected = OPTIONS.find((option) => option.value === selectedOptionValue)
    return (
        <Select value={selectedOptionValue} onValueChange={(value) => value && selectOption(value)}>
            <SelectTrigger className="min-w-32" data-attr="experiment-implementation-language">
                <SelectValue>
                    {() =>
                        selected ? (
                            <span className="flex items-center gap-2">
                                <selected.Icon />
                                {selected.value}
                            </span>
                        ) : (
                            selectedOptionValue
                        )
                    }
                </SelectValue>
            </SelectTrigger>
            <SelectContent>
                {[LibraryType.Client, LibraryType.Server].map((type) => (
                    <SelectGroup key={type}>
                        <SelectGroupLabel>
                            {type === LibraryType.Client ? 'Client libraries' : 'Server libraries'}
                        </SelectGroupLabel>
                        {OPTIONS.filter((option) => option.type === type).map(({ Icon, value }) => (
                            <SelectItem key={value} value={value}>
                                <span className="flex items-center gap-2">
                                    <Icon />
                                    {value}
                                </span>
                            </SelectItem>
                        ))}
                    </SelectGroup>
                ))}
            </SelectContent>
        </Select>
    )
}

function QuillPromptImplementation({
    flagKey,
    promptMetadata,
    onSnippetCopied,
    onAgentPromptCopied,
}: {
    flagKey: string
    promptMetadata: NonNullable<NonNullable<Experiment['parameters']>['prompt_metadata']>
    onSnippetCopied: OnSnippetCopied
    onAgentPromptCopied: () => void
}): JSX.Element {
    const [activeTab, setActiveTab] = useState<PromptImplementationTab>('agent')

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <Heading size="base" render={<h2 className="m-0" />}>
                    Implementation
                </Heading>
                <Text size="xs" variant="muted">
                    Prompt experiment for <b>{promptMetadata.name}</b> ({promptMetadata.templates.join(', ')})
                </Text>
            </div>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                <PromptPayloadHelp />
            </Text>
            <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as PromptImplementationTab)}>
                <TabsList variant="line">
                    <TabsTrigger value="agent">Agent prompt</TabsTrigger>
                    <TabsTrigger value="python">Python</TabsTrigger>
                    <TabsTrigger value="javascript">JavaScript</TabsTrigger>
                </TabsList>
                <TabsContent value="agent" className="flex flex-col gap-2 pt-2">
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {AGENT_PROMPT_HELP}
                    </Text>
                    <PromptExperimentAgentPromptSnippet flagKey={flagKey} onCopy={onAgentPromptCopied} />
                </TabsContent>
                <TabsContent value="python" className="pt-2">
                    <PromptExperimentPythonSnippet
                        flagKey={flagKey}
                        onCopy={() => onSnippetCopied({ sdk: SDKKey.PYTHON, variant: null, snippetKind: 'code' })}
                    />
                </TabsContent>
                <TabsContent value="javascript" className="pt-2">
                    <PromptExperimentJSSnippet
                        flagKey={flagKey}
                        onCopy={() => onSnippetCopied({ sdk: SDKKey.NODE_JS, variant: null, snippetKind: 'code' })}
                    />
                </TabsContent>
            </Tabs>
            <DocsLink to={PROMPT_DOCS_URL}>See the docs for prompt management.</DocsLink>
        </div>
    )
}

function QuillGenericImplementation({
    experiment,
    onSnippetCopied,
}: {
    experiment: Partial<Experiment> | null
    onSnippetCopied: OnSnippetCopied
}): JSX.Element {
    const variants = getExperimentVariants(experiment)
    const [currentVariant, setCurrentVariant] = useState(variants[1]?.key ?? 'test')
    const [selectedOption, setSelectedOption] = useState(OPTIONS[0])

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Heading size="base" render={<h2 className="m-0" />}>
                    Implementation
                </Heading>
                <div className="flex items-center gap-3">
                    <span className="flex items-center gap-2">
                        <Text size="xs" variant="muted" render={<span />}>
                            Variant group
                        </Text>
                        <Select value={currentVariant} onValueChange={(value) => value && setCurrentVariant(value)}>
                            <SelectTrigger className="min-w-24" data-attr="experiment-implementation-variant">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {variants.map((variant: MultivariateFlagVariant) => (
                                    <SelectItem key={variant.key} value={variant.key}>
                                        {variant.key}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </span>
                    <QuillCodeLanguageSelect
                        selectedOptionValue={selectedOption.value}
                        selectOption={(value) => {
                            const option = OPTIONS.find((candidate) => candidate.value === value)
                            if (option) {
                                setSelectedOption(option)
                            }
                        }}
                    />
                </div>
            </div>
            <selectedOption.Snippet
                variant={currentVariant}
                flagKey={experiment?.feature_flag?.key ?? ''}
                onCopy={() =>
                    onSnippetCopied({ sdk: selectedOption.key, variant: currentVariant, snippetKind: 'code' })
                }
                onTestCopy={() =>
                    onSnippetCopied({ sdk: selectedOption.key, variant: currentVariant, snippetKind: 'test_override' })
                }
            />
            <DocsLink to={selectedOption.documentationLink}>See the docs for more implementation information.</DocsLink>
        </div>
    )
}

export function QuillExperimentImplementationDetails({
    experiment,
    placement,
}: {
    experiment: Partial<Experiment> | null
    placement: ImplementationSnippetPlacement
}): JSX.Element {
    const promptMetadata = experiment?.parameters?.prompt_metadata
    const onSnippetCopied: OnSnippetCopied = (copy) => reportImplementationSnippetCopied(experiment, placement, copy)

    if (promptMetadata) {
        return (
            <QuillPromptImplementation
                flagKey={experiment?.feature_flag?.key ?? ''}
                promptMetadata={promptMetadata}
                onSnippetCopied={onSnippetCopied}
                onAgentPromptCopied={() => reportAgentPromptCopied(experiment, placement)}
            />
        )
    }
    return <QuillGenericImplementation experiment={experiment} onSnippetCopied={onSnippetCopied} />
}

export function QuillWebExperimentImplementationDetails({
    experiment,
}: {
    experiment: Partial<Experiment> | null
}): JSX.Element {
    const [open, setOpen] = useState(false)

    return (
        <div className="flex flex-col gap-2">
            <Heading size="base" render={<h2 className="m-0" />}>
                Implementation
            </Heading>
            <Text size="xs" variant="muted">
                {WEB_IMPLEMENTATION_HELP}
            </Text>
            <Button variant="outline" className="self-start" onClick={() => setOpen(true)}>
                Launch toolbar on your website
                <IconOpenInApp />
            </Button>
            <Dialog open={open} onOpenChange={setOpen}>
                <DialogContent size="wide" className="max-w-2xl" data-attr="experiment-toolbar-domain-modal">
                    <DialogHeader>
                        <DialogTitle>Select a domain</DialogTitle>
                        <DialogDescription>{toolbarDomainDescription(!!experiment?.id)}</DialogDescription>
                    </DialogHeader>
                    <DialogBody>
                        {open && (
                            <AuthorizedUrlList
                                experimentId={experiment?.id}
                                type={AuthorizedUrlListType.TOOLBAR_URLS}
                            />
                        )}
                    </DialogBody>
                    <DialogFooter showCloseButton />
                </DialogContent>
            </Dialog>
        </div>
    )
}
