import { AnimatePresence, motion } from 'motion/react'

import { LemonSwitch } from '@posthog/lemon-ui'

interface ScreenEditorCardProps {
    title: string
    enabled: boolean
    onToggle: (enabled: boolean) => void
    children: React.ReactNode
}

export function ScreenEditorCard({ title, enabled, onToggle, children }: ScreenEditorCardProps): JSX.Element {
    return (
        <div className="border border-border rounded-lg bg-bg-light overflow-hidden">
            {/* Always visible header with toggle */}
            <div className="flex items-center justify-between gap-2 px-3 py-2.5">
                <span className="text-sm font-medium">{title}</span>
                <LemonSwitch checked={enabled} onChange={onToggle} aria-label={title} />
            </div>

            {/* Animated expandable content */}
            <AnimatePresence initial={false}>
                {enabled && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2, ease: [0.25, 1, 0.5, 1] }}
                    >
                        <div className="px-3 pb-3 space-y-2 border-t border-border pt-2.5">{children}</div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}
