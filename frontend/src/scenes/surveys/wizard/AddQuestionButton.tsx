import { AnimatePresence } from 'motion/react'
import * as motion from 'motion/react-client'
import { useEffect, useRef, useState } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { SurveyQuestionType } from '~/types'

import { QUESTION_TYPE_OPTIONS } from '../constants'

interface AddQuestionButtonProps {
    onAdd: (type: SurveyQuestionType) => void
}

export function AddQuestionButton({ onAdd }: AddQuestionButtonProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const containerRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        function handleClickOutside(event: MouseEvent): void {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsExpanded(false)
            }
        }

        if (isExpanded) {
            document.addEventListener('mousedown', handleClickOutside)
        }

        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [isExpanded])

    const handleAddQuestion = (type: SurveyQuestionType): void => {
        onAdd(type)
        setIsExpanded(false)
    }

    return (
        <div ref={containerRef} className="relative">
            <AnimatePresence mode="wait">
                {!isExpanded ? (
                    <motion.div
                        key="collapsed"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.15 }}
                    >
                        <LemonButton
                            type="secondary"
                            icon={<IconPlus />}
                            onClick={() => setIsExpanded(true)}
                            fullWidth
                            center
                        >
                            Add question
                        </LemonButton>
                    </motion.div>
                ) : (
                    <motion.div
                        key="expanded"
                        initial={{ opacity: 0, y: -8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -8 }}
                        transition={{
                            type: 'spring',
                            duration: 0.3,
                            bounce: 0.2,
                        }}
                        className="flex flex-wrap gap-2 p-3 border border-border rounded-lg bg-bg-light"
                    >
                        <div className="w-full flex items-center justify-between mb-1">
                            <p className="text-xs text-secondary">Select question type</p>
                            <LemonButton
                                icon={<IconX />}
                                size="xsmall"
                                type="tertiary"
                                onClick={() => setIsExpanded(false)}
                                tooltip="Cancel"
                            />
                        </div>
                        {QUESTION_TYPE_OPTIONS.map((option, index) => (
                            <motion.div
                                key={option.type}
                                initial={{ opacity: 0, scale: 0.8 }}
                                animate={{ opacity: 1, scale: 1 }}
                                transition={{
                                    type: 'spring',
                                    duration: 0.25,
                                    bounce: 0.3,
                                    delay: index * 0.03,
                                }}
                            >
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={option.icon}
                                    onClick={() => handleAddQuestion(option.type)}
                                >
                                    {option.label}
                                </LemonButton>
                            </motion.div>
                        ))}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}
