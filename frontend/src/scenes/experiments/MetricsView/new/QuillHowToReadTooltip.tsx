import { PreviewCard } from '@base-ui/react/preview-card'

import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { HOW_TO_READ_URL, HowToReadContent } from './HowToReadTooltip'

export function QuillHowToReadTooltip(): JSX.Element {
    return (
        <PreviewCard.Root>
            <PreviewCard.Trigger
                delay={300}
                closeDelay={100}
                render={
                    <Button
                        variant="link-muted"
                        size="sm"
                        nativeButton={false}
                        render={<LinkPrimitive to={HOW_TO_READ_URL} target="_blank" />}
                    />
                }
            >
                How to read
            </PreviewCard.Trigger>
            <PreviewCard.Portal>
                <PreviewCard.Positioner data-quill data-quill-portal="popover" side="top" sideOffset={8}>
                    <PreviewCard.Popup className="max-w-sm origin-[var(--transform-origin)] rounded-md border border-border bg-card p-4 text-xs text-foreground shadow-[var(--shadow-md)] outline-none transition-[opacity,scale] duration-150 ease-out data-[ending-style]:scale-97 data-[ending-style]:opacity-0 data-[starting-style]:scale-97 data-[starting-style]:opacity-0 motion-reduce:transition-none">
                        <HowToReadContent
                            wonClassName="text-success-foreground"
                            lostClassName="text-destructive-foreground"
                        />
                    </PreviewCard.Popup>
                </PreviewCard.Positioner>
            </PreviewCard.Portal>
        </PreviewCard.Root>
    )
}
