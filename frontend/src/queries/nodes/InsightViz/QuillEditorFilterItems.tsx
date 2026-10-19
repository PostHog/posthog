import { IconInfo } from '@posthog/icons'
import { Field, FieldTitle, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { InsightEditorFilter, InsightLogicProps } from '~/types'

export interface QuillEditorFilterItemsProps {
    editorFilters: InsightEditorFilter[]
    insightProps: InsightLogicProps
}

export function QuillEditorFilterItems({ editorFilters, insightProps }: QuillEditorFilterItemsProps): JSX.Element {
    return (
        <>
            {editorFilters.map(({ label: Label, tooltip, showOptional, key, component: Component }) => (
                <Field key={key} className="gap-2">
                    {Label ? (
                        <FieldTitle>
                            {typeof Label === 'function' ? <Label insightProps={insightProps} /> : Label}
                            {showOptional ? (
                                <Text size="xs" variant="muted" render={<span />}>
                                    (optional)
                                </Text>
                            ) : null}
                            {tooltip ? (
                                <Tooltip>
                                    <TooltipTrigger
                                        render={<span className="inline-flex" tabIndex={0} aria-label="More info" />}
                                    >
                                        <IconInfo className="size-4 text-muted-foreground" />
                                    </TooltipTrigger>
                                    <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
                                </Tooltip>
                            ) : null}
                        </FieldTitle>
                    ) : null}
                    {Component ? (
                        <div data-not-quill className="min-w-0">
                            <Component insightProps={insightProps} />
                        </div>
                    ) : null}
                </Field>
            ))}
        </>
    )
}
