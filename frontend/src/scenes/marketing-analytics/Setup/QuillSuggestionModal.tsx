import { IconMinus, IconPlus } from '@posthog/icons'
import {
    Button,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaDescription,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    Text,
} from '@posthog/quill'

import type { DiffLine } from './applyDiff'

const CHANGE_CLASS: Record<DiffLine['change'], string> = {
    add: 'text-success-foreground',
    remove: 'text-destructive-foreground',
    update: 'text-muted-foreground',
}

export function QuillSuggestionModal({
    title,
    logo,
    description,
    explanation,
    noopMessage,
    lines,
    changeLabels,
    batchTitles,
    urlFixSnippet,
    confirmLabel,
    confirmDestructive,
    isApplying,
    onConfirm,
    onClose,
}: {
    title: string
    logo: JSX.Element | null
    description: string
    /** Set for navigate-only ops, which have no diff to preview. */
    explanation: string | null
    noopMessage: string | null
    lines: DiffLine[]
    changeLabels: Record<DiffLine['change'], string>
    batchTitles: { id: string; title: string }[]
    urlFixSnippet: string | null
    confirmLabel: string
    confirmDestructive: boolean
    isApplying: boolean
    onConfirm: () => void
    onClose: () => void
}): JSX.Element {
    return (
        <Credenza open onOpenChange={(open) => !open && onClose()}>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle className="flex items-center gap-2">
                        {logo}
                        <span>{title}</span>
                    </CredenzaTitle>
                    <CredenzaDescription>{description}</CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody>
                    <div className="flex flex-col gap-3">
                        {explanation ? (
                            <Text size="xs" render={<p className="m-0" />}>
                                {explanation}
                            </Text>
                        ) : noopMessage ? (
                            <Item tone="info" size="sm">
                                <ItemContent>
                                    <ItemDescription>{noopMessage}</ItemDescription>
                                </ItemContent>
                            </Item>
                        ) : (
                            <div className="flex flex-col gap-1">
                                <Heading size="sm" render={<h4 className="m-0" />}>
                                    This will change
                                </Heading>
                                <div className="flex flex-col divide-y divide-border rounded-md border border-border px-3">
                                    {lines.map((line, index) => (
                                        <div key={index} className="flex items-start gap-2 py-1.5">
                                            <span className="mt-0.5 shrink-0">
                                                {line.change === 'add' ? (
                                                    <IconPlus className={CHANGE_CLASS.add} />
                                                ) : line.change === 'remove' ? (
                                                    <IconMinus className={CHANGE_CLASS.remove} />
                                                ) : (
                                                    <span className="font-mono text-xs text-muted-foreground">~</span>
                                                )}
                                            </span>
                                            <div className="min-w-0 flex-1">
                                                <div className="text-xs text-muted-foreground">
                                                    <span className={`font-semibold ${CHANGE_CLASS[line.change]}`}>
                                                        {changeLabels[line.change]}
                                                    </span>
                                                    {` · ${line.setting}`}
                                                    {line.subject ? ` · ${line.subject}` : ''}
                                                </div>
                                                <div className="font-mono text-sm break-all">
                                                    {line.change === 'update' ? (
                                                        <>
                                                            <span className="text-muted-foreground line-through">
                                                                {line.before}
                                                            </span>
                                                            <span className="mx-1.5 text-muted-foreground">→</span>
                                                            <span>{line.after}</span>
                                                        </>
                                                    ) : (
                                                        <span
                                                            className={
                                                                line.change === 'remove'
                                                                    ? 'text-muted-foreground line-through'
                                                                    : undefined
                                                            }
                                                        >
                                                            {line.after}
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {batchTitles.length > 0 && (
                            <ul className="m-0 list-disc pl-4 text-xs text-muted-foreground">
                                {batchTitles.map((item) => (
                                    <li key={item.id}>{item.title}</li>
                                ))}
                            </ul>
                        )}

                        {urlFixSnippet !== null && (
                            <Item tone="warning" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        A mapping works around the tagging, it doesn't fix it. The lasting fix is to tag
                                        the ad URLs with <code className="font-mono">{urlFixSnippet}</code> in the
                                        platform.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        )}
                    </div>
                </CredenzaBody>
                <CredenzaFooter>
                    {/* Pins initial focus to a control that opens no tooltip. */}
                    <Button variant="outline" onClick={onClose} autoFocus>
                        Cancel
                    </Button>
                    <Button
                        variant={confirmDestructive ? 'destructive' : 'primary'}
                        loading={isApplying}
                        onClick={onConfirm}
                    >
                        {confirmLabel}
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
