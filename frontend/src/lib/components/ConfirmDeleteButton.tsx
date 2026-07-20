import { AnimatePresence, useReducedMotion } from 'motion/react'
import * as motion from 'motion/react-client'
import { useEffect, useState } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

const CONFIRM_RESET_MS = 5000

interface ConfirmDeleteButtonProps {
    onDelete: () => void
    idleLabel?: string
    confirmLabel?: string
    'data-attr'?: string
}

export function ConfirmDeleteButton({
    onDelete,
    idleLabel = 'Delete',
    confirmLabel = 'Confirm?',
    'data-attr': dataAttr,
}: ConfirmDeleteButtonProps): JSX.Element {
    const [armed, setArmed] = useState(false)
    const reduceMotion = useReducedMotion()

    useEffect(() => {
        if (!armed) {
            return
        }
        const handle = window.setTimeout(() => setArmed(false), CONFIRM_RESET_MS)
        return () => window.clearTimeout(handle)
    }, [armed])

    const handleClick = (): void => {
        if (armed) {
            onDelete()
            setArmed(false)
        } else {
            setArmed(true)
        }
    }

    return (
        <div className="relative isolate inline-block overflow-hidden rounded">
            <AnimatePresence>
                {armed && (
                    <motion.div
                        key="timer"
                        className="absolute inset-0 -z-10 bg-danger/20 origin-left"
                        initial={{ scaleX: 1 }}
                        animate={{ scaleX: reduceMotion ? 1 : 0 }}
                        exit={{ opacity: 0, transition: { duration: reduceMotion ? 0 : 0.12 } }}
                        transition={{
                            duration: reduceMotion ? 0 : CONFIRM_RESET_MS / 1000,
                            ease: 'linear',
                        }}
                    />
                )}
            </AnimatePresence>
            <LemonButton size="small" icon={<IconTrash />} status="danger" data-attr={dataAttr} onClick={handleClick}>
                {armed ? confirmLabel : idleLabel}
            </LemonButton>
            <span aria-live="polite" aria-atomic="true" className="sr-only">
                {armed ? `Press again within ${CONFIRM_RESET_MS / 1000} seconds to confirm deletion.` : ''}
            </span>
        </div>
    )
}
