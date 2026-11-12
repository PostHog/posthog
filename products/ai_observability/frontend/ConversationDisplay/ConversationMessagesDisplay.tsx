import clsx from 'clsx'
import { useValues } from 'kea'
import React from 'react'

import { IconCode, IconEye, IconMarkdown, IconMarkdownFilled, IconWrench } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { HighlightedJSONViewer } from 'lib/components/HighlightedJSONViewer'
import { IconExclamation, IconEyeHidden } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { isObject } from 'lib/utils/guards'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { aiBlobRenderHandlers, resolveAiBlobUrl, resolveDataUri } from '../aiBlob'
import { AIImage } from '../components/AIImage'
import { getJsonContainerForDisplay, JSONValueDisplay } from '../components/JSONValueDisplay'
import { LLMInputOutput } from '../LLMInputOutput'
import { isRedactedMediaSentinel, isRenderableMediaSource, redactedMediaKind } from '../mediaSource'
import { CompatMessage, MultiModalContentItem, VercelSDKImageMessage } from '../types'
import {
    aiTokenCount,
    describeStopReason,
    getGeminiInlineData,
    hasStringContentField,
    isAnthropicDocumentMessage,
    isAnthropicImageMessage,
    isGeminiAudioMessage,
    isGeminiDocumentMessage,
    isGeminiImageMessage,
    isOpenAIAudioMessage,
    isOpenAIFileMessage,
    isOpenAIImageURLMessage,
    looksLikeXml,
    parseToolArgumentsForDisplay,
} from '../utils'
import { MessageActionsMenu } from './MessageActionsMenu'
import { MessageActionsMenuProvider } from './MessageActionsMenuProvider'
import { RedactedMediaPlaceholder } from './RedactedMediaPlaceholder'
import { XMLViewer } from './XMLViewer'

type MessageType = 'input' | 'output'

function getInitialMessageShowStates(
    inputMessages: CompatMessage[],
    outputMessages: CompatMessage[]
): { input: boolean[]; output: boolean[] } {
    return {
        input: inputMessages.map((_, i) => i === inputMessages.length - 1),
        output: outputMessages.map(() => true),
    }
}

function billedTokenCount(value: unknown): number | null {
    const count = aiTokenCount(value)
    return count !== null && count > 0 ? count : null
}

// Explains a generation that rendered no content. `$ai_stop_reason` is the provider's own account of
// why it stopped, so it outranks anything inferred from token counts. Providers disagree on whether
// reasoning tokens sit inside the output count or beside it, so name each count that is present
// rather than deriving one from the other.
function describeEmptyOutput(
    outputTokens: unknown,
    reasoningTokens: unknown,
    textOutputTokens: unknown,
    stopReason: unknown
): string | null {
    const output = billedTokenCount(outputTokens)
    const reasoning = billedTokenCount(reasoningTokens)
    const namedCause = describeStopReason(stopReason)
    const textOutput = aiTokenCount(textOutputTokens)

    // Providers disagree on where reasoning tokens are counted. OpenAI-style providers count them
    // inside the output total, so reasoning can never exceed output there, and matching counts mean
    // the whole output was reasoning. Gemini-style providers count them separately, so a reasoning
    // count above a nonzero output count can only come from that style, which means the output
    // tokens are real content that went missing. `$ai_text_output_tokens` is the provider's own
    // split and needs no inference: zero means nothing textual was generated, under either style.
    const providerSaysNoText = textOutput === 0 && output !== null
    const reasoningMatchesOutput = textOutput === null && output !== null && reasoning !== null && reasoning === output

    const counts = [
        output !== null ? `${humanFriendlyNumber(output)} output tokens` : null,
        // When the counts match, listing both reads as two amounts. One number, one claim about it.
        reasoning !== null && !reasoningMatchesOutput ? `${humanFriendlyNumber(reasoning)} reasoning tokens` : null,
    ].filter(Boolean)

    // A provider can block a response before billing anything, so a known cause stands on its own.
    if (counts.length === 0) {
        return namedCause
    }

    const cause =
        namedCause ??
        (providerSaysNoText
            ? 'None of them were text.'
            : reasoningMatchesOutput
              ? 'All of them may have been reasoning.'
              : output === null && reasoning !== null
                ? 'The model may have spent its budget on reasoning.'
                : 'The response may have been cut short, or the SDK may not have captured it.')

    return `The provider reported ${counts.join(' and ')} but no content was captured. ${cause}`
}

export function ConversationMessagesDisplay({
    inputNormalized,
    outputNormalized,
    errorData,
    httpStatus,
    raisedError,
    outputTokens,
    reasoningTokens,
    textOutputTokens,
    stopReason,
    bordered = false,
    traceId,
    eventId,
}: {
    inputNormalized: CompatMessage[]
    outputNormalized: CompatMessage[]
    errorData: any
    httpStatus?: number
    raisedError?: boolean
    /** `$ai_output_tokens`, used to explain an output the provider billed for but never sent. */
    outputTokens?: unknown
    /** `$ai_reasoning_tokens`. Some providers bill only these, so they alone can explain an empty output. */
    reasoningTokens?: unknown
    /** `$ai_text_output_tokens`. An explicit zero says every billed output token was reasoning. */
    textOutputTokens?: unknown
    /** `$ai_stop_reason`. The provider's own account of why it stopped, so it outranks any inference. */
    stopReason?: unknown
    bordered?: boolean
    traceId?: string | null
    eventId?: string
}): JSX.Element {
    const [messageShowStates, setMessageShowStates] = React.useState(() =>
        getInitialMessageShowStates(inputNormalized, outputNormalized)
    )
    const [isRenderingMarkdown, setIsRenderingMarkdown] = React.useState(true)
    const [isRenderingXml, setIsRenderingXml] = React.useState(false)
    const inputRolesSignature = inputNormalized.map((message) => message.role).join('|')
    const outputRolesSignature = outputNormalized.map((message) => message.role).join('|')
    const inputMessageShowStates = messageShowStates.input
    const outputMessageShowStates = messageShowStates.output

    const toggleMessage = (type: MessageType, index: number): void => {
        setMessageShowStates((state) => {
            const nextTypeState = [...state[type]]
            if (index < 0 || index >= nextTypeState.length) {
                return state
            }
            nextTypeState[index] = !nextTypeState[index]
            return { ...state, [type]: nextTypeState }
        })
    }

    const showAllMessages = (type: MessageType): void => {
        setMessageShowStates((state) => ({ ...state, [type]: state[type].map(() => true) }))
    }

    const hideAllMessages = (type: MessageType): void => {
        setMessageShowStates((state) => ({ ...state, [type]: state[type].map(() => false) }))
    }

    // Initialize message states when the messages change.
    React.useEffect(() => {
        setMessageShowStates(getInitialMessageShowStates(inputNormalized, outputNormalized))
    }, [
        inputNormalized.length,
        outputNormalized.length,
        inputRolesSignature,
        outputRolesSignature,
        outputNormalized,
        inputNormalized,
    ])

    const allInputsExpanded = inputMessageShowStates.every(Boolean)
    const allInputsCollapsed = inputMessageShowStates.every((state: boolean) => !state)

    const inputButtons =
        inputNormalized.length > 0 ? (
            <div className="flex items-center gap-1">
                <LemonButton
                    size="xsmall"
                    onClick={() => showAllMessages('input')}
                    icon={<IconEye />}
                    disabledReason={allInputsExpanded ? 'All inputs are already expanded' : undefined}
                >
                    Expand all
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    onClick={() => hideAllMessages('input')}
                    icon={<IconEyeHidden />}
                    disabledReason={allInputsCollapsed ? 'All inputs are already collapsed' : undefined}
                >
                    Collapse all
                </LemonButton>
            </div>
        ) : undefined

    const allOutputsExpanded = outputMessageShowStates.every(Boolean)
    const allOutputsCollapsed = outputMessageShowStates.every((state: boolean) => !state)

    const outputButtons =
        outputNormalized.length > 0 ? (
            <div className="flex items-center gap-1">
                <LemonButton
                    size="xsmall"
                    onClick={() => showAllMessages('output')}
                    icon={<IconEye />}
                    disabledReason={allOutputsExpanded ? 'All outputs are already expanded' : undefined}
                >
                    Expand all
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    onClick={() => hideAllMessages('output')}
                    icon={<IconEyeHidden />}
                    disabledReason={allOutputsCollapsed ? 'All outputs are already collapsed' : undefined}
                >
                    Collapse all
                </LemonButton>
            </div>
        ) : undefined

    const inputDisplay =
        inputNormalized.length > 0 ? (
            inputNormalized.map((message, i) => (
                <React.Fragment key={i}>
                    <LLMMessageDisplay
                        actionMenuKey={`input-${i}`}
                        message={message}
                        show={inputMessageShowStates[i] || false}
                        onToggle={() => toggleMessage('input', i)}
                        traceId={traceId}
                        isRenderingMarkdown={isRenderingMarkdown}
                        isRenderingXml={isRenderingXml}
                        onToggleMarkdownRendering={() => setIsRenderingMarkdown((state) => !state)}
                        onToggleXmlRendering={() => setIsRenderingXml((state) => !state)}
                    />
                    {i < inputNormalized.length - 1 && (
                        <div className="border-l ml-2 h-2" /> /* Spacer connecting messages visually */
                    )}
                </React.Fragment>
            ))
        ) : (
            <div className="rounded border text-default p-2 italic bg-[var(--bg-fill-error-tertiary)]">No input</div>
        )

    const showOutputSection = outputNormalized.length > 0 || !raisedError

    // Nothing to render means the provider either charged for work whose content never reached the
    // event, or told us why it stopped. Name that, so an empty box isn't mistaken for a provider
    // that said nothing.
    const emptyOutputExplanation =
        outputNormalized.length === 0
            ? describeEmptyOutput(outputTokens, reasoningTokens, textOutputTokens, stopReason)
            : null

    return (
        <MessageActionsMenuProvider
            resetKey={`${eventId ?? ''}:${traceId ?? ''}:${inputRolesSignature}:${outputRolesSignature}`}
        >
            <LLMInputOutput
                inputDisplay={inputDisplay}
                outputDisplay={
                    showOutputSection ? (
                        outputNormalized.length > 0 ? (
                            outputNormalized.map((message, i) => (
                                <LLMMessageDisplay
                                    key={i}
                                    actionMenuKey={`output-${i}`}
                                    message={message}
                                    show={outputMessageShowStates[i] || false}
                                    isOutput
                                    onToggle={() => toggleMessage('output', i)}
                                    traceId={traceId}
                                    isRenderingMarkdown={isRenderingMarkdown}
                                    isRenderingXml={isRenderingXml}
                                    onToggleMarkdownRendering={() => setIsRenderingMarkdown((state) => !state)}
                                    onToggleXmlRendering={() => setIsRenderingXml((state) => !state)}
                                />
                            ))
                        ) : (
                            <div className="rounded border text-default p-2 bg-[var(--bg-fill-error-tertiary)]">
                                <div className="italic">No output</div>
                                {emptyOutputExplanation && (
                                    <div className="mt-1 text-xs" data-attr="ai-empty-output-explanation">
                                        {emptyOutputExplanation}{' '}
                                        <Link
                                            to="https://posthog.com/docs/ai-observability/troubleshooting#why-does-my-generation-show-no-output"
                                            target="_blank"
                                        >
                                            Learn more
                                        </Link>
                                    </div>
                                )}
                            </div>
                        )
                    ) : null
                }
                outputHeading={showOutputSection ? 'Output' : undefined}
                bordered={bordered}
                inputButtons={inputButtons}
                outputButtons={showOutputSection ? outputButtons : undefined}
            />
            {raisedError && errorData && (
                <div className="mt-4">
                    <h4 className="flex items-center justify-between text-xs font-semibold mb-2">
                        <div className="flex items-center gap-x-1.5">
                            <IconExclamation className="text-base text-danger" />
                            Error {httpStatus ? `(${httpStatus})` : ''}
                        </div>
                    </h4>
                    <div className="flex items-center gap-1.5 rounded border text-default p-2 font-medium bg-[var(--bg-fill-error-tertiary)] border-danger overflow-x-auto">
                        {isObject(errorData) ? (
                            <HighlightedJSONViewer src={errorData} collapsed={4} />
                        ) : (
                            <span className="font-mono">
                                {(() => {
                                    try {
                                        const parsedJson = JSON.parse(errorData)
                                        return isObject(parsedJson) ? (
                                            <HighlightedJSONViewer src={parsedJson} collapsed={5} />
                                        ) : (
                                            JSON.stringify(errorData ?? null)
                                        )
                                    } catch {
                                        return JSON.stringify(errorData ?? null)
                                    }
                                })()}
                            </span>
                        )}
                    </div>
                </div>
            )}
        </MessageActionsMenuProvider>
    )
}

type ImageDisplayMessage = { content?: string | { type?: string; image?: string } }

function getImageDisplayMessage(value: Record<string, unknown>): ImageDisplayMessage | null {
    if (value.type === 'input_image') {
        return typeof value.image_url === 'string' ? { content: { type: 'image', image: value.image_url } } : null
    }

    if (value.type !== 'image') {
        return null
    }

    if (typeof value.content === 'string') {
        return { content: value.content }
    }

    if (isObject(value.content) && typeof value.content.image === 'string') {
        return {
            content: {
                type: typeof value.content.type === 'string' ? value.content.type : 'image',
                image: value.content.image,
            },
        }
    }

    return typeof value.image === 'string' ? { content: { type: 'image', image: value.image } } : null
}

export const ImageMessageDisplay = ({ message }: { message: ImageDisplayMessage }): JSX.Element => {
    const { currentTeamId } = useValues(teamLogic)
    const { content } = message

    if (typeof content === 'string') {
        return <span>{content}</span>
    } else if (content?.image) {
        if (isRedactedMediaSentinel(content.image)) {
            return <RedactedMediaPlaceholder kind="image" />
        }
        if (!isRenderableMediaSource(content.image)) {
            return <HighlightedJSONViewer src={content} name={null} collapsed={5} />
        }
        const src = resolveAiBlobUrl(content.image, currentTeamId)
        return (
            <AIImage
                src={src}
                alt="User sent image"
                fallback={<HighlightedJSONViewer src={content} name={null} collapsed={5} />}
            />
        )
    }

    return <span>{String(content ?? '')}</span>
}

function renderContentItem(item: MultiModalContentItem, currentTeamId: number | string | null): JSX.Element | null {
    if (typeof item === 'string') {
        return <span className="whitespace-pre-wrap">{item}</span>
    }

    // File and audio parts carry a filename or transcript alongside the payload, so those kinds are
    // replaced inside their own branch to keep that content. An image part is only the image.
    const redacted = redactedMediaKind(item)
    if (redacted === 'image') {
        return <RedactedMediaPlaceholder kind="image" />
    }

    if (!item || typeof item !== 'object' || !('type' in item)) {
        return <HighlightedJSONViewer src={item} name={null} collapsed={5} />
    }

    if (
        (item.type === 'text' || item.type === 'input_text' || item.type === 'output_text') &&
        'text' in item &&
        typeof item.text === 'string'
    ) {
        return <span className="whitespace-pre-wrap">{item.text}</span>
    }

    if (item.type === 'image' && 'image' in item && typeof item.image === 'string') {
        return <ImageMessageDisplay message={{ content: { type: 'image', image: item.image } }} />
    }

    if (item.type === 'input_image' && typeof item.image_url === 'string') {
        return <ImageMessageDisplay message={{ content: { type: 'image', image: item.image_url } }} />
    }

    if (isOpenAIImageURLMessage(item)) {
        if (!isRenderableMediaSource(item.image_url.url)) {
            return <HighlightedJSONViewer src={item} name={null} collapsed={5} />
        }
        const src = resolveAiBlobUrl(item.image_url.url, currentTeamId)
        return (
            <AIImage
                src={src}
                alt="Message content"
                className="max-w-full max-h-[400px] rounded"
                fallback={<HighlightedJSONViewer src={item} name={null} collapsed={5} />}
            />
        )
    }

    if (isAnthropicImageMessage(item)) {
        const src = resolveDataUri(item.source.data, item.source.media_type, currentTeamId)
        return (
            <AIImage
                src={src}
                alt="Message content"
                className="max-w-full max-h-[400px] rounded"
                fallback={<HighlightedJSONViewer src={item} name={null} collapsed={5} />}
            />
        )
    }

    if (isGeminiImageMessage(item)) {
        const inlineData = getGeminiInlineData(item)
        const src = inlineData
            ? resolveDataUri(inlineData.data, inlineData.mime_type, currentTeamId)
            : typeof item.uri === 'string' && isRenderableMediaSource(item.uri)
              ? resolveAiBlobUrl(item.uri, currentTeamId)
              : null
        if (!src) {
            return <HighlightedJSONViewer src={item} name={null} collapsed={5} />
        }
        return (
            <AIImage
                src={src}
                alt="Message content"
                className="max-w-full max-h-[400px] rounded"
                fallback={<HighlightedJSONViewer src={item} name={null} collapsed={5} />}
            />
        )
    }

    if (isOpenAIFileMessage(item)) {
        if (redacted === 'file') {
            return <RedactedMediaPlaceholder kind="file" filename={item.file.filename} />
        }
        const resolved = resolveAiBlobUrl(item.file.file_data, currentTeamId)
        if (resolved === item.file.file_data && !item.file.file_data.startsWith('data:')) {
            return <span className="text-muted">{item.file.filename}</span>
        }
        return (
            // eslint-disable-next-line react/forbid-elements
            <a href={resolved} download={item.file.filename} className="text-link hover:underline">
                {item.file.filename}
            </a>
        )
    }

    if (isAnthropicDocumentMessage(item)) {
        if (redacted === 'file') {
            return <RedactedMediaPlaceholder kind="file" />
        }
        const href = resolveDataUri(item.source.data, item.source.media_type, currentTeamId)
        const fileName = `document.${item.source.media_type.split('/')[1] || 'bin'}`
        return (
            // eslint-disable-next-line react/forbid-elements
            <a href={href} download={fileName} className="text-link hover:underline">
                {fileName}
            </a>
        )
    }

    if (isGeminiDocumentMessage(item)) {
        if (redacted === 'file') {
            return <RedactedMediaPlaceholder kind="file" />
        }
        const inlineData = getGeminiInlineData(item)
        if (!inlineData) {
            return null
        }
        const href = resolveDataUri(inlineData.data, inlineData.mime_type, currentTeamId)
        const fileName = `document.${inlineData.mime_type.split('/')[1] || 'bin'}`
        return (
            // eslint-disable-next-line react/forbid-elements
            <a href={href} download={fileName} className="text-link hover:underline">
                {fileName}
            </a>
        )
    }

    if (isOpenAIAudioMessage(item) || isGeminiAudioMessage(item)) {
        const mimeType = 'mime_type' in item ? item.mime_type : undefined
        const transcript = 'transcript' in item ? item.transcript : undefined
        const src = resolveDataUri(item.data, mimeType ?? 'audio/wav', currentTeamId)

        return (
            <div className="space-y-2">
                {redacted === 'audio' ? (
                    <RedactedMediaPlaceholder kind="audio" />
                ) : (
                    <audio controls className="w-[500px]" src={src} {...aiBlobRenderHandlers(src, 'audio')} />
                )}
                {transcript && typeof transcript === 'string' && (
                    <div className="text-xs text-muted p-2 bg-bg-light rounded border">
                        <div className="font-semibold mb-1">Transcript:</div>
                        <div className="whitespace-pre-wrap">{transcript}</div>
                    </div>
                )}
            </div>
        )
    }

    if (
        item.type === 'function' &&
        item.function &&
        typeof item.function === 'object' &&
        typeof item.function.name === 'string'
    ) {
        const { name, arguments: rawArgs } = item.function
        const callId = 'id' in item && typeof item.id === 'string' ? item.id : undefined
        const args = parseToolArgumentsForDisplay(rawArgs)
        const displayName = name || '(unnamed function)'

        return (
            <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-xs">
                    <IconWrench className="text-muted shrink-0" />
                    <span className="font-mono font-semibold">{displayName}</span>
                    {callId && <span className="font-mono text-muted truncate">{callId}</span>}
                </div>
                {args.kind === 'parsed' && <HighlightedJSONViewer src={args.value} name={null} collapsed={5} />}
                {args.kind === 'raw' && <pre className="font-mono whitespace-pre-wrap text-xs m-0">{args.value}</pre>}
            </div>
        )
    }

    return <HighlightedJSONViewer src={item} name={null} collapsed={5} />
}

/** Max characters to render in minimal (table preview) mode. */
const MINIMAL_PREVIEW_LIMIT = 500

/** Extract a plain-text preview from message content, truncated for table cells. */
function extractMinimalPreview(content: string | { type: string; content: string } | MultiModalContentItem[]): string {
    let text: string
    if (typeof content === 'string') {
        text = content
    } else if (Array.isArray(content)) {
        text = content
            .map((item) => {
                if (typeof item === 'string') {
                    return item
                }
                if (item && typeof item === 'object') {
                    if ('text' in item && typeof item.text === 'string') {
                        return item.text
                    }
                    if ('transcript' in item && typeof item.transcript === 'string') {
                        return item.transcript
                    }
                }
                return ''
            })
            .filter(Boolean)
            .join(' ')
    } else if (hasStringContentField(content)) {
        text = content.content
    } else {
        text = JSON.stringify(content)
    }

    if (text.length > MINIMAL_PREVIEW_LIMIT) {
        return text.slice(0, MINIMAL_PREVIEW_LIMIT) + '…'
    }
    return text
}

export const LLMMessageDisplay = React.memo(
    ({
        message,
        isOutput,
        show = true,
        minimal = false,
        onToggle,
        traceId,
        isRenderingMarkdown = true,
        isRenderingXml = false,
        onToggleMarkdownRendering,
        onToggleXmlRendering,
        actionMenuKey,
    }: {
        message: CompatMessage
        isOutput?: boolean
        /** @default true */
        show?: boolean
        /** In minimal mode, we don't show the role, toggles, or additional kwargs, and reduce padding. */
        minimal?: boolean
        onToggle?: () => void
        traceId?: string | null
        isRenderingMarkdown?: boolean
        isRenderingXml?: boolean
        onToggleMarkdownRendering?: () => void
        onToggleXmlRendering?: () => void
        actionMenuKey?: string
    }): JSX.Element => {
        const { currentTeamId } = useValues(teamLogic)
        const { role, content, ...additionalKwargs } = message
        const parsedJsonContainer =
            !show || Array.isArray(content)
                ? null
                : getJsonContainerForDisplay(content, { allowEmptyContainers: false })
        const displayContent =
            Array.isArray(parsedJsonContainer) &&
            parsedJsonContainer.some((item) => redactedMediaKind(item) === 'image')
                ? (parsedJsonContainer as MultiModalContentItem[])
                : content
        const isRedactedImage = redactedMediaKind(parsedJsonContainer) === 'image'
        let resolvedIsRenderingMarkdown = isRenderingMarkdown
        let resolvedIsRenderingXml = isRenderingXml

        if (minimal) {
            resolvedIsRenderingMarkdown = true
            resolvedIsRenderingXml = false
        }

        // Compute whether the content looks like Markdown.
        // (Heuristic: looks for code blocks, blockquotes, headings, italic, bold, underline, strikethrough)
        const isMarkdownCandidate =
            content && typeof content === 'string' ? /(\n\s*```|^>\s|#{1,6}\s|_|\*|~~)/.test(content) : false

        // Compute whether the content looks like XML
        const isXmlCandidate = looksLikeXml(content)

        // Render any additional keyword arguments as JSON.
        const additionalKwargsEntries = Array.isArray(additionalKwargs.tools)
            ? // Tools are a special case of input - and we want name and description to show first for them!
              additionalKwargs.tools.map((tool) => {
                  // Handle both formats: {function: {name, description, ...}} and {toolName, toolCallType, ...}
                  if (tool.function) {
                      const { function: { name = undefined, description = undefined, ...func } = {}, ...rest } = tool
                      return {
                          function: { name, description, ...func },
                          ...rest,
                      }
                  }
                  return tool
              })
            : Object.fromEntries(Object.entries(additionalKwargs).filter(([, value]) => value !== undefined))

        const renderMessageContent = (
            content: string | { type: string; content: string } | VercelSDKImageMessage | MultiModalContentItem[]
        ): JSX.Element | null => {
            if (!content) {
                return null
            }

            // Handle array-based content
            if (Array.isArray(content)) {
                return (
                    <>
                        {content.map((item, index) => (
                            <React.Fragment key={index}>
                                {renderContentItem(item, currentTeamId)}
                                {index < content.length - 1 && <div className="border-t my-2" />}
                            </React.Fragment>
                        ))}
                    </>
                )
            }
            if (parsedJsonContainer) {
                if (isObject(parsedJsonContainer)) {
                    const imageMessage = getImageDisplayMessage(parsedJsonContainer)
                    if (imageMessage) {
                        return <ImageMessageDisplay message={imageMessage} />
                    }
                    if (parsedJsonContainer.type === 'output_text' && 'text' in parsedJsonContainer) {
                        return <span className="whitespace-pre-wrap">{String(parsedJsonContainer.text)}</span>
                    }
                }
                return <JSONValueDisplay value={parsedJsonContainer} collapsed={5} />
            }

            // If the content appears to be XML, render based on the toggle.
            if (isXmlCandidate && typeof content === 'string') {
                if (resolvedIsRenderingXml) {
                    return <XMLViewer collapsed={3}>{content}</XMLViewer>
                }
                return <span className="font-mono whitespace-pre-wrap">{content}</span>
            }

            // If the content appears to be Markdown, render based on the toggle.
            if (isMarkdownCandidate && typeof content === 'string') {
                if (resolvedIsRenderingMarkdown) {
                    // Check if content has HTML-like tags that might break markdown rendering
                    const hasHtmlLikeTags = /<[^>]+>/.test(content)

                    if (hasHtmlLikeTags) {
                        // Escape HTML-like content for safer markdown rendering
                        const escapedContent = content.replace(/</g, '&lt;').replace(/>/g, '&gt;')

                        try {
                            // pre-wrap, because especially in system prompts, we want to preserve newlines even if they aren't fully Markdown-style
                            return <LemonMarkdown className="whitespace-pre-wrap">{escapedContent}</LemonMarkdown>
                        } catch {
                            // If markdown still fails, fall back to plain text
                            return <span className="font-mono whitespace-pre-wrap">{content}</span>
                        }
                    } else {
                        // pre-wrap, because especially in system prompts, we want to preserve newlines even if they aren't fully Markdown-style
                        return <LemonMarkdown className="whitespace-pre-wrap">{content}</LemonMarkdown>
                    }
                } else {
                    return <span className="font-mono whitespace-pre-wrap">{content}</span>
                }
            }

            // Fallback: render as plain text.
            const contentStr = typeof content === 'string' ? content : JSON.stringify(content)
            return <span className="whitespace-pre-wrap">{contentStr}</span>
        }

        return (
            <div
                className={clsx(
                    'border text-default min-w-[min(fit-content,8rem)]',
                    !minimal ? 'rounded' : 'rounded-sm text-xs max-w-50 max-h-50 overflow-y-auto',
                    isOutput
                        ? 'bg-[var(--color-bg-fill-success-tertiary)] not-last:mb-2'
                        : role === 'user'
                          ? 'bg-[var(--color-bg-fill-tertiary)]'
                          : role.startsWith('assistant')
                            ? 'bg-[var(--color-bg-fill-info-tertiary)]'
                            : null
                )}
            >
                {!minimal && (
                    <div
                        className={clsx(
                            'flex items-center gap-1 w-full px-2 h-6 text-xs font-medium select-none',
                            onToggle && 'cursor-pointer'
                        )}
                        onClick={(e) => {
                            const clickedButton = (e.target as Element).closest('button')
                            if (!clickedButton) {
                                onToggle?.()
                            }
                        }}
                    >
                        <span className="grow flex items-center gap-1.5">{role}</span>
                        {(content || Object.keys(additionalKwargsEntries).length > 0) && (
                            <>
                                <LemonButton
                                    size="small"
                                    noPadding
                                    icon={show ? <IconEyeHidden /> : <IconEye />}
                                    tooltip="Toggle message content"
                                    onClick={onToggle}
                                />
                                {isMarkdownCandidate && (
                                    <LemonButton
                                        size="small"
                                        noPadding
                                        icon={resolvedIsRenderingMarkdown ? <IconMarkdownFilled /> : <IconMarkdown />}
                                        tooltip="Toggle markdown rendering"
                                        onClick={onToggleMarkdownRendering}
                                    />
                                )}
                                {isXmlCandidate && role !== 'tool' && role !== 'tools' && (
                                    <LemonButton
                                        size="small"
                                        noPadding
                                        icon={<IconCode />}
                                        tooltip="Toggle XML syntax highlighting"
                                        onClick={onToggleXmlRendering}
                                        active={resolvedIsRenderingXml}
                                    />
                                )}
                                <CopyToClipboardInline
                                    iconSize="small"
                                    description="message content"
                                    explicitValue={typeof content === 'string' ? content : JSON.stringify(content)}
                                />
                                <MessageActionsMenu
                                    menuKey={actionMenuKey}
                                    content={
                                        typeof content === 'string' ? content : (JSON.stringify(content, null, 2) ?? '')
                                    }
                                    traceId={traceId}
                                />
                            </>
                        )}
                    </div>
                )}
                {show && !!content && (
                    <div className={!minimal ? 'p-2 border-t' : 'p-1'}>
                        {isRedactedImage ? (
                            <RedactedMediaPlaceholder kind="image" />
                        ) : minimal ? (
                            <LemonMarkdown className="whitespace-pre-wrap">
                                {extractMinimalPreview(displayContent)}
                            </LemonMarkdown>
                        ) : (
                            renderMessageContent(displayContent)
                        )}
                    </div>
                )}
                {show && (!minimal || !content) && Object.keys(additionalKwargsEntries).length > 0 && (
                    <div className={clsx(!minimal ? 'p-2 text-xs border-t' : 'p-1 text-xs')}>
                        <HighlightedJSONViewer src={additionalKwargsEntries} name={null} collapsed={5} />
                    </div>
                )}
            </div>
        )
    }
)

LLMMessageDisplay.displayName = 'LLMMessageDisplay'
