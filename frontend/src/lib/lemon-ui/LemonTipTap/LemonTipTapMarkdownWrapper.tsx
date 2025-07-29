import React, { useState } from 'react'
import { LemonTipTapMarkdown } from './LemonTipTapMarkdown'
import { LemonTextAreaProps } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'

/**
 * Wrapper that handles both legacy text and rich content
 * This demonstrates the migration path from text to rich content
 */
export const LemonTipTapMarkdownWrapper = React.forwardRef<HTMLDivElement, LemonTextAreaProps>(
    function LemonTipTapMarkdownWrapper({ value, onChange, ...props }, ref) {
        const [richContent, setRichContent] = useState<any>(null)

        return (
            <LemonTipTapMarkdown
                ref={ref}
                value={value}
                richContent={richContent}
                onChange={onChange}
                onRichContentChange={setRichContent}
                {...props}
            />
        )
    }
)
